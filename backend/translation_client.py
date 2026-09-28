"""
translation_client.py
─────────────────────
Google Cloud Translation API (v2 "Basic") for sentence-level translation.

• v2 is used because it needs no project/location resource paths and has
  the lowest per-request overhead for short sentences. The client is
  blocking, so each call runs in a worker thread via asyncio.to_thread.

• Both target translations (→ Sinhala, → Tamil) are fired concurrently with
  asyncio.gather, so caption latency is one round-trip, not two.

• Pass-through: if the detected source language already IS the target
  language, the original text is returned without calling the API.

• STT returns codes such as "si-LK", "ta-lk" or "en-US"; Translation wants
  ISO-639-1 ("si", "ta", "en"), so the region suffix is stripped.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from google.cloud import translate_v2 as translate

log = logging.getLogger("translate")

LANG_SINHALA = "si"
LANG_TAMIL = "ta"

_client: translate.Client | None = None
_client_lock = threading.Lock()


def get_translate_client() -> translate.Client:
    """Process-wide client. Credentials come from GOOGLE_APPLICATION_CREDENTIALS."""
    global _client
    with _client_lock:
        if _client is None:
            _client = translate.Client()
        return _client


def normalise_lang(stt_code: str) -> str:
    return (stt_code or "").split("-")[0].lower()


async def translate_text(text: str, target_language: str, source_language_code: str) -> str:
    source = normalise_lang(source_language_code)
    if source == target_language or not text.strip():
        return text

    result = await asyncio.to_thread(
        get_translate_client().translate,
        text,
        target_language=target_language,
        source_language=source or None,
        format_="text",
    )
    return result.get("translatedText", text)


async def translate_to_sinhala_and_tamil(
    text: str, source_language_code: str
) -> tuple[str | None, str | None]:
    """
    Returns (sinhala, tamil). Either may be `text` itself when passed through,
    or None if that one translation failed — the other line is still shown.
    """
    results = await asyncio.gather(
        translate_text(text, LANG_SINHALA, source_language_code),
        translate_text(text, LANG_TAMIL, source_language_code),
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
