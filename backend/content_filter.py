"""
Caption content filter.

Every line shown to the audience (original transcript, Sinhala, Tamil,
interim and final) passes through `content_filter.check()`. Misheard speech
can come out of Google as an obscene word, and translation can turn an
innocent phrase into one, so the original is filtered before translation
and both translations after it.

Matching runs on a "match key" of each word: NFC, zero-width joiners
removed, case-folded, and letters the recogniser confuses folded together
(ණ/න, ළ/ල, ෂ/ශ, ථ/ත, ධ/ද, ඟ/ංග, long/short vowel signs; ண/ந/ன, ற/ர,
ள/ழ/ல), so a variant spelling of a blocked word still matches.

  exact    — whole word only (short words that are also the start of
             innocent words, e.g. පක vs පක්ෂය)
  prefix   — word stem; catches every inflected form (ලිංගික → ලිංගිකත්වය)
  contains — anywhere inside a word; catches compounds (සමලිංගික)
  phrases  — multi-word sequences
Also blocked:
  • any word containing "*" (Google's profanity mask, "f***")
  • a word the recogniser split in two ("හුත් තා") — short pieces are rejoined
  • in live previews, an unfinished last word that is the start of a
    blocked word ("ලිංගි…"), so it never flashes up before completion

FILTER_ACTION=drop hides the whole caption; mask replaces each word with "…".
blocklist.json is re-read automatically when edited (no restart needed).
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass

import config

log = logging.getLogger("filter")

MASK = "…"
_INVISIBLE = {ord(c): None for c in "\u200b\u200c\u200d\u2060\ufeff"}
_CONFUSABLE = {
    # Sinhala: aspirated/retroflex/prenasalised letters and long vowel signs
    "ණ": "න", "ළ": "ල", "ෂ": "ශ", "ථ": "ත", "ධ": "ද", "ඛ": "ක", "ඝ": "ග",
    "ඵ": "ප", "භ": "බ", "ඡ": "ච", "ඣ": "ජ", "ඨ": "ට", "ඪ": "ඩ",
    "ඟ": "ංග", "ඬ": "ංඩ", "ඳ": "ංද", "ඹ": "ංබ",
    "ී": "ි", "ූ": "ු", "ේ": "ෙ", "ෝ": "ො", "ෑ": "ැ", "ෲ": "ෘ",
    # Tamil: nasals, r-sounds, l-sounds
    "ண": "ன", "ந": "ன", "ற": "ர", "ள": "ல", "ழ": "ல",
}
_FOLD = {**_INVISIBLE, **{ord(k): v for k, v in _CONFUSABLE.items()}}
_DELIMS = r"\s.,!?;:\"'“”‘’()\[\]{}…\-–—/\\|।"
_TOKEN_RE = re.compile(rf"[^{_DELIMS}]+")
_MASK_RUN_RE = re.compile(r"…(?:\s*…)+")
_RELOAD_CHECK_S = 5.0
# Pieces this short (code points) are rejoined with the next word.
_FRAGMENT_MAX = 4
# Unfinished last word in a preview must be at least this long to be held.
_PARTIAL_MIN = 3


def normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold().translate(_FOLD)


@dataclass
class FilterResult:
    text: str
    blocked: int
    confirmed: bool = False  # False when only an unfinished preview word was held

    @property
    def dropped(self) -> bool:
        return self.blocked > 0 and not self.text


class ContentFilter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._exact: frozenset[str] = frozenset()
        self._prefix: tuple[str, ...] = ()
        self._contains: tuple[str, ...] = ()
        self._phrases: list[tuple[str, ...]] = []
        self._stems: tuple[str, ...] = ()
        self._mtime = 0.0
        self._checked_at = 0.0
        self.loaded = False
        self._load()

    def _load(self) -> None:
        path = config.BLOCKLIST_PATH
        try:
            mtime = path.stat().st_mtime
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.error("Blocklist NOT loaded from %s (%s) — captions are unfiltered", path, exc)
            return
        exact: set[str] = set()
        prefix: set[str] = set()
        contains: set[str] = set()
        phrases: list[tuple[str, ...]] = []
        for key, group in data.items():
            if key.startswith("_") or not isinstance(group, dict):
                continue
            for kind, target in (("exact", exact), ("prefix", prefix), ("contains", contains)):
                for entry in group.get(kind, []):
                    words = [normalize(w) for w in _TOKEN_RE.findall(entry)]
                    if len(words) == 1:
                        target.add(words[0])
                    elif len(words) > 1:
                        phrases.append(tuple(words))
            for entry in group.get("phrases", []):
                words = tuple(normalize(w) for w in _TOKEN_RE.findall(entry))
                if words:
                    phrases.append(words)
        with self._lock:
            self._exact = frozenset(exact)
            self._prefix = tuple(sorted(prefix))
            self._contains = tuple(sorted(contains))
            self._phrases = phrases
            self._stems = tuple(sorted(exact | prefix | contains))
            self._mtime = mtime
            self.loaded = True
        log.info(
            "Blocklist loaded: %d exact, %d stems, %d roots, %d phrases",
            len(exact), len(prefix), len(contains), len(phrases),
        )
        self._self_check()

    def _self_check(self) -> None:
        """Warn if any event vocabulary hint would itself be blocked."""
        try:
            hints = json.loads(config.PHRASES_PATH.read_text(encoding="utf-8")).get("phrases", [])
        except Exception:
            return
        values = [h["value"] if isinstance(h, dict) else str(h) for h in hints]
        clashes = [v for v in values if any(self._scan(v, interim=False)[1])]
        if clashes:
            log.warning("Blocklist also blocks %d event phrase(s): %s", len(clashes), ", ".join(clashes))

    def _maybe_reload(self) -> None:
        now = time.monotonic()
        if now - self._checked_at < _RELOAD_CHECK_S:
            return
        self._checked_at = now
        try:
            if config.BLOCKLIST_PATH.stat().st_mtime != self._mtime:
                self._load()
        except OSError:
            pass

    def _bad_word(self, key: str) -> bool:
        return (
            "*" in key
            or key in self._exact
            or key.startswith(self._prefix)
            or any(root in key for root in self._contains)
        )

    def _unfinished_bad(self, key: str) -> bool:
        if len(key) < _PARTIAL_MIN:
            return False
        if any(len(stem) > len(key) and stem.startswith(key) for stem in self._stems):
            return True
        # A root may begin mid-word: "homosex…" → "sexual", "සමලිං…" → "ලිංග".
        return any(
            key.endswith(root[:k])
            for root in self._contains
            for k in range(_PARTIAL_MIN, len(root))
        )

    def _scan(self, text: str, interim: bool) -> tuple[list[tuple[int, int]], list[bool], bool]:
        spans = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
        keys = [normalize(text[s:e]) for s, e in spans]
        bad = [self._bad_word(k) for k in keys]
        for i in range(len(keys) - 1):
            a, b = keys[i], keys[i + 1]
            # Sinhala/Tamil only: rejoining English words makes false hits ("his hit").
            if (
                min(len(a), len(b)) <= _FRAGMENT_MAX
                and not (a.isascii() or b.isascii())
                and self._bad_word(a + b)
            ):
                bad[i] = bad[i + 1] = True
        for phrase in self._phrases:
            n = len(phrase)
            for i in range(len(keys) - n + 1):
                if tuple(keys[i:i + n]) == phrase:
                    for j in range(i, i + n):
                        bad[j] = True
        partial = False
        # Google punctuates previews ("…homose."), so the last word of any
        # preview may still be unfinished.
        if interim and keys and not bad[-1]:
            partial = bad[-1] = self._unfinished_bad(keys[-1])
        return spans, bad, partial

    def check(self, text: str, interim: bool = False) -> FilterResult:
        if not config.FILTER_ENABLED or not text:
            return FilterResult(text, 0)
        self._maybe_reload()
        spans, bad, partial = self._scan(text, interim)
        blocked = sum(bad)
        if not blocked:
            return FilterResult(text, 0)
        confirmed = blocked > int(partial)
        if config.FILTER_ACTION == "drop":
            return FilterResult("", blocked, confirmed)
        out = []
        pos = 0
        for (start, end), is_bad in zip(spans, bad):
            if is_bad:
                out.append(text[pos:start])
                out.append(MASK)
                pos = end
        out.append(text[pos:])
        return FilterResult(_MASK_RUN_RE.sub(MASK, "".join(out)), blocked, confirmed)


content_filter = ContentFilter()
