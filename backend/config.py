"""
Central runtime settings. PROFILE and MODE drive cost vs quality.
Defaults favour ECO so daily testing does not burn credit.
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).parent


def _bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


PROFILE = os.getenv("PROFILE", "eco").strip().lower()  # eco | event
if PROFILE not in {"eco", "event"}:
    PROFILE = "eco"

MODE = os.getenv("MODE", "live").strip().lower()  # live | cache
if MODE not in {"live", "cache"}:
    MODE = "live"

# Recognition strategy: 0 = single stream + alternatives (ECO scout)
#                       1 = parallel streams + window arbiter (EVENT default)
#                       2 = word-level fusion (experimental, off)
ARBITER_STRATEGY = _int("ARBITER_STRATEGY", 1 if PROFILE == "event" else 0)
if ARBITER_STRATEGY not in {0, 1, 2}:
    ARBITER_STRATEGY = 0
ENABLE_STRATEGY_2 = _bool("ENABLE_STRATEGY_2", "false")
if ARBITER_STRATEGY == 2 and not ENABLE_STRATEGY_2:
    ARBITER_STRATEGY = 1

PARALLEL_LANGUAGES = [
    c.strip()
    for c in os.getenv("PARALLEL_LANGUAGES", "si-LK,ta-IN,en-US").split(",")
    if c.strip()
]
PRIMARY_LANGUAGE = os.getenv("STT_PRIMARY_LANGUAGE", "si-LK")
ALTERNATIVE_LANGUAGES = [
    c.strip()
    for c in os.getenv("STT_ALTERNATIVE_LANGUAGES", "ta-LK,en-US").split(",")
    if c.strip()
]

STT_MODEL = os.getenv("STT_MODEL", "default")
AUTO_PUNCTUATION = _bool("STT_AUTO_PUNCTUATION", "true")
ENABLE_WORD_CONFIDENCE = _bool("STT_WORD_CONFIDENCE", "true")
ENABLE_WORD_TIME_OFFSETS = _bool("STT_WORD_TIME_OFFSETS", "true")

SOFT_ROTATE_S = _int("STT_SESSION_RESTART_INTERVAL", 240)
HARD_ROTATE_S = min(SOFT_ROTATE_S + 40, 290)
ENDPOINT_SILENCE_MS = _int("STT_ENDPOINT_SILENCE_MS", 700)
MAX_UTTERANCE_S = _float("STT_MAX_UTTERANCE_S", 15.0)

# Spectral denoise is OFF by default — latency + ASR artefacts (A5).
NOISE_REDUCTION_STRENGTH = _float("NOISE_REDUCTION_STRENGTH", 0.0)
ENABLE_NORMALIZE = _bool("ENABLE_NORMALIZE", "true")

# VAD / session gating (E1–E3)
VAD_ENABLED = _bool("VAD_ENABLED", "true")
VAD_AGGRESSIVENESS = _int("VAD_AGGRESSIVENESS", 2)  # webrtcvad 0–3
VAD_PREROLL_MS = _int("VAD_PREROLL_MS", 500)
VAD_HANGOVER_MS = _int("VAD_HANGOVER_MS", 900)
VAD_MIN_SPEECH_MS = _int("VAD_MIN_SPEECH_MS", 250)
IDLE_CLOSE_SECONDS = _float("IDLE_CLOSE_SECONDS", 12.0)
IDLE_PAUSE_SECONDS = _float("IDLE_PAUSE_SECONDS", 180.0)
NOISE_BURN_SECONDS = _float("NOISE_BURN_SECONDS", 60.0)

# Translation
TRANSLATE_TIMEOUT_S = _float("TRANSLATE_TIMEOUT_S", 4.0)
TRANSLATE_PROGRESSIVE = PROFILE == "event" or _bool("TRANSLATE_PROGRESSIVE", "false")
TRANSLATE_MIN_INTERVAL_MS = _int("TRANSLATE_MIN_INTERVAL_MS", 350)
TRANSLATE_CACHE = _bool("TRANSLATE_CACHE", "true")

# Budget (E7) — ECO hard-stops; EVENT only warns
DAILY_BUDGET_USD = _float("DAILY_BUDGET_USD", 10.0)
TOTAL_BUDGET_USD = _float("TOTAL_BUDGET_USD", 250.0)
BUDGET_HARD_STOP = PROFILE == "eco"

# Paths
PHRASES_PATH = ROOT / os.getenv("PHRASES_FILE", "phrases.json")
PRICING_PATH = ROOT / os.getenv("PRICING_FILE", "pricing.json")
LEDGER_PATH = ROOT / os.getenv("LEDGER_FILE", "usage_ledger.json")
TRANSLATE_CACHE_PATH = ROOT / ".cache" / "translations.json"
CACHE_FIXTURES_PATH = ROOT / "fixtures" / "cache_mode.json"

SAMPLE_RATE_HZ = 16_000
CHUNK_BYTES = 3200  # 100 ms LINEAR16 mono


def is_event() -> bool:
    return PROFILE == "event"


def is_eco() -> bool:
    return PROFILE == "eco"


def is_cache_mode() -> bool:
    return MODE == "cache"


def summary() -> dict:
    return {
        "profile": PROFILE,
        "mode": MODE,
        "arbiter_strategy": ARBITER_STRATEGY,
        "parallel_languages": PARALLEL_LANGUAGES,
        "vad_enabled": VAD_ENABLED,
        "noise_reduction": NOISE_REDUCTION_STRENGTH,
        "translate_progressive": TRANSLATE_PROGRESSIVE,
        "daily_budget_usd": DAILY_BUDGET_USD,
        "total_budget_usd": TOTAL_BUDGET_USD,
        "budget_hard_stop": BUDGET_HARD_STOP,
    }
