"""
Google Cloud Translation v2 (Basic).

Why v2: lowest overhead for short captions, no location resource path,
mature client. Long-lived process-wide client; warmed at startup.
Disk cache keyed by (text, source, target) so repeated rehearsals cost $0.
Mixed-script runs are segmented and translated with an explicit source.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
from pathlib import Path

from google.cloud import translate_v2 as translate

import config
from usage_ledger import ledger

log = logging.getLogger("translate")

LANG_SINHALA = "si"
LANG_TAMIL = "ta"

_SINHALA = re.compile(r"[\u0D80-\u0DFF]+")
_TAMIL = re.compile(r"[\u0B80-\u0BFF]+")
_LATIN = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")

_client: translate.Client | None = None
_client_lock = threading.Lock()
_cache: dict[str, str] = {}
_cache_lock = threading.Lock()
_cache_loaded = False


def get_translate_client() -> translate.Client:
    global _client
    with _client_lock:
        if _client is None:
            _client = translate.Client()
        return _client


def normalise_lang(stt_code: str) -> str:
    return (stt_code or "").split("-")[0].lower()


def _cache_key(text: str, source: str, target: str) -> str:
    return f"{source}|{target}|{text}"


def _load_cache() -> None:
    global _cache_loaded, _cache
    if _cache_loaded or not config.TRANSLATE_CACHE:
        return
    path: Path = config.TRANSLATE_CACHE_PATH
    if path.is_file():
        try:
            _cache = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    _cache_loaded = True


def _persist_cache() -> None:
    if not config.TRANSLATE_CACHE:
        return
    path: Path = config.TRANSLATE_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")


def segment_by_script(text: str) -> list[tuple[str, str]]:
    """Split into (source_lang, run_text) preserving order."""
    if not text:
        return []
    runs: list[tuple[str, str]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if _SINHALA.match(ch):
            m = _SINHALA.match(text, i)
            runs.append(("si", m.group(0)))
            i = m.end()
        elif _TAMIL.match(ch):
            m = _TAMIL.match(text, i)
            runs.append(("ta", m.group(0)))
            i = m.end()
        elif _LATIN.match(ch):
            m = _LATIN.match(text, i)
            runs.append(("en", m.group(0)))
            i = m.end()
        else:
            # punctuation / digits / spaces attach to previous run
            if runs:
                lang, prev = runs[-1]
                runs[-1] = (lang, prev + ch)
            else:
                runs.append(("en", ch))
            i += 1
    # merge adjacent same-lang
    merged: list[tuple[str, str]] = []
    for lang, part in runs:
        if merged and merged[-1][0] == lang:
            merged[-1] = (lang, merged[-1][1] + part)
        else:
            merged.append((lang, part))
    return merged


async def _call_api(text: str, target: str, source: str) -> str:
    def _do():
        return get_translate_client().translate(
            text,
            target_language=target,
            source_language=source or None,
            format_="text",
        )

    last_err: Exception | None = None
    for attempt in range(2):
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_do),
                timeout=config.TRANSLATE_TIMEOUT_S,
            )
            return result.get("translatedText", text)
        except Exception as exc:
            last_err = exc
            if attempt == 0:
                await asyncio.sleep(0.15)
    raise last_err  # type: ignore


async def translate_text(text: str, target_language: str, source_language_code: str) -> str:
    source = normalise_lang(source_language_code)
    text = (text or "").strip()
    if not text or source == target_language:
        return text

    _load_cache()
    key = _cache_key(text, source, target_language)
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    if config.is_cache_mode():
        return text  # no API in cache mode for unknown strings

    ok, _ = ledger.allow_google()
    if not ok:
        return text

    translated = await _call_api(text, target_language, source)
    ledger.record_translate(len(text))
    with _cache_lock:
        _cache[key] = translated
        _persist_cache()
    return translated


async def translate_mixed(text: str, target_language: str, fallback_source: str) -> str:
    """Translate a mixed-script string run-by-run (D1)."""
    runs = segment_by_script(text)
    if not runs:
        return ""
    # single-run fast path
    if len(runs) == 1:
        return await translate_text(runs[0][1], target_language, runs[0][0] or fallback_source)

    parts = await asyncio.gather(
        *[translate_text(part, target_language, lang) for lang, part in runs],
        return_exceptions=True,
    )
    out = []
    for (lang, part), result in zip(runs, parts):
        if isinstance(result, BaseException):
            log.error("Run translate %s→%s failed: %s", lang, target_language, result)
            out.append(part)
        else:
            out.append(result)
    return " ".join(p.strip() for p in out if p.strip())


async def translate_to_sinhala_and_tamil(
    text: str, source_language_code: str
) -> tuple[str | None, str | None]:
    results = await asyncio.gather(
        translate_mixed(text, LANG_SINHALA, source_language_code),
        translate_mixed(text, LANG_TAMIL, source_language_code),
        return_exceptions=True,
    )
    outputs: list[str | None] = []
    for target, result in zip((LANG_SINHALA, LANG_TAMIL), results):
        if isinstance(result, BaseException):
            log.error("Translation to %s failed: %s", target, result)
            outputs.append(None)
        else:
            outputs.append(result)
    return outputs[0], outputs[1]


async def warm_client() -> None:
    """Dummy call at startup so the first real caption is not cold."""
    if config.is_cache_mode():
        return
    try:
        t0 = time.perf_counter()
        await asyncio.wait_for(
            asyncio.to_thread(
                get_translate_client().translate,
                "ok",
                target_language="si",
                source_language="en",
                format_="text",
            ),
            timeout=5,
        )
        log.info("Translate client warmed in %.0f ms", (time.perf_counter() - t0) * 1000)
        ledger.record_translate(2)
    except Exception as exc:
        log.warning("Translate warm-up skipped: %s", exc)
