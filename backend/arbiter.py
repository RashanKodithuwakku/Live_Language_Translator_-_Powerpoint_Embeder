"""
Transcript arbiter (C2).

Strategy 0: passthrough of a single scout stream (handled upstream).
Strategy 1: per-utterance pick best stream by confidence × script consistency.
Strategy 2: word-level fusion (experimental; ENABLE_STRATEGY_2=true).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

log = logging.getLogger("arbiter")

_SINHALA = re.compile(r"[\u0D80-\u0DFF]")
_TAMIL = re.compile(r"[\u0B80-\u0BFF]")
_LATIN = re.compile(r"[A-Za-z]")

_SCRIPT_FOR = {
    "si": "si",
    "si-lk": "si",
    "ta": "ta",
    "ta-lk": "ta",
    "ta-in": "ta",
    "en": "en",
    "en-us": "en",
    "en-gb": "en",
}


def script_tag(lang: str) -> str:
    return _SCRIPT_FOR.get((lang or "").lower(), "en")


def script_consistency(text: str, lang: str) -> float:
    if not text:
        return 0.0
    letters = [c for c in text if c.isalpha() or _SINHALA.match(c) or _TAMIL.match(c)]
    if not letters:
        return 0.5
    tag = script_tag(lang)
    if tag == "si":
        hits = sum(1 for c in letters if _SINHALA.match(c))
    elif tag == "ta":
        hits = sum(1 for c in letters if _TAMIL.match(c))
    else:
        hits = sum(1 for c in letters if _LATIN.match(c))
    return hits / len(letters)


@dataclass
class StreamHypothesis:
    language: str
    text: str
    is_final: bool
    confidence: float = 0.0
    stability: float = 0.0
    words: list[dict] = field(default_factory=list)  # {word, start, end, conf}


@dataclass
class ArbiterResult:
    text: str
    language: str
    is_final: bool
    confidence: float
    chosen_from: str
    debug: dict = field(default_factory=dict)


# Below this script consistency the preferred stream's text is treated as
# a misrecognition (e.g. English speech forced into Sinhala), so the other
# streams may win on score.
PREFERRED_MIN_CONSISTENCY = 0.4


class Arbiter:
    def __init__(self, strategy: int = 1, hysteresis: float = 0.08, preferred: str | None = None) -> None:
        self.strategy = strategy
        self.hysteresis = hysteresis
        self.preferred = preferred
        self._last_lang: str | None = preferred

    def set_preferred(self, lang: str | None) -> None:
        self.preferred = lang
        self._last_lang = lang

    def preferred_hyp(self, hyps: list[StreamHypothesis]) -> StreamHypothesis | None:
        # si and ta streams both emit confident, script-consistent text for
        # either language, so score alone can't tell them apart: the
        # operator's speaker choice decides unless its transcript is broken.
        if not self.preferred:
            return None
        tag = script_tag(self.preferred)
        pref = next((h for h in hyps if script_tag(h.language) == tag), None)
        if pref and script_consistency(pref.text, pref.language) >= PREFERRED_MIN_CONSISTENCY:
            return pref
        return None

    def score(self, hyp: StreamHypothesis) -> float:
        conf = hyp.confidence if hyp.confidence > 0 else 0.55
        return conf * (0.35 + 0.65 * script_consistency(hyp.text, hyp.language))

    def choose(self, hyps: list[StreamHypothesis]) -> ArbiterResult | None:
        hyps = [h for h in hyps if h.text.strip()]
        if not hyps:
            return None
        if self.strategy == 0 or len(hyps) == 1:
            h = hyps[0]
            return ArbiterResult(h.text, h.language, h.is_final, h.confidence, h.language)

        if self.strategy == 2:
            return self._fuse_words(hyps)

        ranked = sorted(hyps, key=self.score, reverse=True)
        best = ranked[0]
        pref = self.preferred_hyp(hyps)
        if pref:
            best = pref
        elif self._last_lang:
            current = next((h for h in ranked if script_tag(h.language) == script_tag(self._last_lang)), None)
            if current and self.score(best) - self.score(current) < self.hysteresis:
                best = current
        self._last_lang = best.language
        debug = {
            "scores": {h.language: round(self.score(h), 3) for h in hyps},
            "chosen": best.language,
            "preferred": self.preferred,
        }
        return ArbiterResult(
            best.text, best.language, best.is_final, best.confidence, best.language, debug
        )

    def _fuse_words(self, hyps: list[StreamHypothesis]) -> ArbiterResult:
        # Prefer streams that already supply word timings; otherwise fall back to Strategy 1.
        if not any(h.words for h in hyps):
            self.strategy = 1
            result = self.choose(hyps)
            self.strategy = 2
            return result  # type: ignore

        # Bucket by approximate 200 ms windows and pick best matching word.
        buckets: dict[int, list[tuple[StreamHypothesis, dict]]] = {}
        for h in hyps:
            for w in h.words:
                key = int(float(w.get("start", 0)) * 5)  # 200 ms
                buckets.setdefault(key, []).append((h, w))
        parts: list[str] = []
        langs: list[str] = []
        for key in sorted(buckets):
            candidates = buckets[key]
            best_h, best_w = max(
                candidates,
                key=lambda pair: (pair[1].get("conf", 0.5) * script_consistency(pair[1].get("word", ""), pair[0].language)),
            )
            word = best_w.get("word", "").strip()
            if word:
                parts.append(word)
                langs.append(best_h.language)
        text = " ".join(parts)
        lang = max(set(langs), key=langs.count) if langs else hyps[0].language
        is_final = all(h.is_final for h in hyps)
        return ArbiterResult(text, lang, is_final, 0.7, "fused", {"strategy": 2})
