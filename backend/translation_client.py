"""
translation_client.py
──────────────────────
Wraps Google Cloud Translation API v2 (Basic) for sentence-level translation.

Design decisions
────────────────
• We use the REST-based `google-cloud-translate` v3 (Advanced) client but
  call it via asyncio.to_thread so the blocking HTTP call doesn't stall the
  event loop.  This is simpler than maintaining an async HTTP session and
  avoids the overhead of the v3 Translation API's project/location path
  requirements for a single-machine event tool.

• Language-passthrough logic:
    If the detected source language already IS the target language, we skip
    the API call and return the original text unchanged.  This is important
    because Google charges per character and, more importantly, translating
    a language to itself introduces unnecessary latency.

• Concurrent translation:
    The caller should use asyncio.gather() to fire both translations
    (→ Sinhala and → Tamil) simultaneously.  This module exposes a single
    coroutine `translate_text()` that makes one API call; the caller is
    responsible for parallelism.

• Source language normalisation:
    Google STT returns codes like "si-LK", "ta-IN", "en-US".
    Google Translate expects BCP-47 language tags like "si", "ta", "en".
    We strip the region suffix before passing to the Translation API.
"""

import asyncio
import os
from functools import lru_cache

from google.cloud import translate_v2 as translate


# ── Language constants ───────────────────────────────────────────────────────
LANG_SINHALA = "si"
LANG_TAMIL = "ta"
LANG_ENGLISH = "en"

# Map of STT language codes → Translation language codes
_STT_TO_TRANSLATE: dict[str, str] = {
    "si-lk": LANG_SINHALA,
    "ta-lk": LANG_TAMIL,
    "ta-in": LANG_TAMIL,
    "en-us": LANG_ENGLISH,
    "en-gb": LANG_ENGLISH,
    "en": LANG_ENGLISH,
    "si": LANG_SINHALA,
    "ta": LANG_TAMIL,
}


# ── Module-level singleton client ────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_translate_client() -> translate.Client:
    """
    Creates and caches the Translation API client.
    Credentials are read automatically from GOOGLE_APPLICATION_CREDENTIALS.
    """
    return translate.Client()


# ── Helper ───────────────────────────────────────────────────────────────────
def _normalise_lang(stt_code: str) -> str:
    """
    Convert an STT language code to a Translation API language code.
    Falls back to the first two characters (ISO 639-1) if no explicit
    mapping exists.
    """
    normalised = _STT_TO_TRANSLATE.get(stt_code.lower())
    if normalised:
        return normalised
    # Fallback: strip region suffix (e.g. "fr-FR" → "fr")
    return stt_code.split("-")[0].lower()


# ── Public API ───────────────────────────────────────────────────────────────
async def translate_text(
    text: str,
    target_language: str,
    source_language_code: str,
) -> str:
    """
    Translate `text` into `target_language`.

    Args:
        text:                 The sentence to translate.
        target_language:      BCP-47 code for the target ("si", "ta", "en").
        source_language_code: The STT-returned language code of the source
                              (e.g. "si-LK", "en-US").  We normalise it
                              internally.

    Returns:
        The translated string, or `text` unchanged if source == target.
    """
    source_lang = _normalise_lang(source_language_code)

    # Skip API call if source and target are the same language
    if source_lang == target_language:
        return text

    if not text.strip():
        return text

    client = get_translate_client()

    # Run the blocking HTTP call in a thread pool so asyncio stays unblocked
    result = await asyncio.to_thread(
        client.translate,
        text,
        target_language=target_language,
        source_language=source_lang,
        format_="text",
    )

    return result.get("translatedText", text)


async def translate_to_sinhala_and_tamil(
    text: str,
    source_language_code: str,
) -> tuple[str, str]:
    """
    Translate `text` into both Sinhala and Tamil concurrently.

    Returns:
        (sinhala_translation, tamil_translation)
        Either may equal `text` if source matches target.
    """
    sinhala_coro = translate_text(text, LANG_SINHALA, source_language_code)
    tamil_coro = translate_text(text, LANG_TAMIL, source_language_code)

    sinhala, tamil = await asyncio.gather(sinhala_coro, tamil_coro)
    return sinhala, tamil
