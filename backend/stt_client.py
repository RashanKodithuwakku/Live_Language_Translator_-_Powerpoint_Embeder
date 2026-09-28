"""
Google Cloud Speech-to-Text v1 streaming client.

Supports:
  • Strategy 0 scout: one stream with alternative_language_codes
  • Strategy 1/2: one stream per language, no alternatives
  • Interim + final results with confidence / stability / word timings
  • Seamless soft/hard rotation before Google's ~305 s limit
  • Local endpointing (silence rotation) for slow si/ta models
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from google.cloud import speech

import config
from arbiter import Arbiter, ArbiterResult, StreamHypothesis, script_tag

log = logging.getLogger("stt")

FINAL_GATHER_S = config._float("STT_FINAL_GATHER_MS", 900) / 1000

_speech_client: speech.SpeechClient | None = None
_client_lock = threading.Lock()
_phrases_cache: list | None = None


def get_speech_client() -> speech.SpeechClient:
    global _speech_client
    with _client_lock:
        if _speech_client is None:
            _speech_client = speech.SpeechClient()
            log.info("Speech client ready (model default=%s)", config.STT_MODEL)
        return _speech_client


def _load_phrases() -> list:
    global _phrases_cache
    if _phrases_cache is not None:
        return _phrases_cache
    path: Path = config.PHRASES_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        phrases = data.get("phrases", data if isinstance(data, list) else [])
        _phrases_cache = [
            speech.SpeechContext(
                phrases=[p["value"] if isinstance(p, dict) else str(p)],
                boost=float(p.get("boost", 10) if isinstance(p, dict) else 10),
            )
            for p in phrases
            if (p.get("value") if isinstance(p, dict) else p)
        ]
        log.info("Loaded %d speech_contexts from %s", len(_phrases_cache), path.name)
    except Exception as exc:
        log.warning("phrases.json not loaded (%s) — continuing without hints", exc)
        _phrases_cache = []
    return _phrases_cache


def _build_config(primary: str, use_alternatives: bool) -> speech.StreamingRecognitionConfig:
    alts = []
    if use_alternatives:
        # Include the default primary so e.g. a Tamil or English speaker
        # setting still has Sinhala as a fallback.
        pool = [config.PRIMARY_LANGUAGE, *config.ALTERNATIVE_LANGUAGES]
        prefix = primary.split("-")[0].lower()
        for c in pool:
            if c.split("-")[0].lower() != prefix and c not in alts:
                alts.append(c)
    # si-LK / ta-* only support default / command_and_search in v1.
    model = config.STT_MODEL
    log.debug("STT config primary=%s model=%s alts=%s", primary, model, alts)
    kwargs = dict(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=config.SAMPLE_RATE_HZ,
        audio_channel_count=1,
        language_code=primary,
        alternative_language_codes=alts,
        enable_automatic_punctuation=config.AUTO_PUNCTUATION,
        model=model,
        speech_contexts=_load_phrases(),
    )
    if config.ENABLE_WORD_CONFIDENCE:
        kwargs["enable_word_confidence"] = True
    if config.ENABLE_WORD_TIME_OFFSETS:
        kwargs["enable_word_time_offsets"] = True
    return speech.StreamingRecognitionConfig(
        config=speech.RecognitionConfig(**kwargs),
        interim_results=True,
        single_utterance=False,
    )


def _duration_s(d) -> float:
    # proto-plus exposes Duration fields as datetime.timedelta.
    if d is None:
        return 0.0
    if hasattr(d, "total_seconds"):
        return float(d.total_seconds())
    return float(getattr(d, "seconds", 0)) + float(getattr(d, "nanos", 0)) / 1e9


@dataclass
class TranscriptEvent:
    text: str
    language_code: str
    is_final: bool
    confidence: float = 0.0
    stability: float = 0.0
    words: list[dict] = field(default_factory=list)
    stream_lang: str = ""
    t_google_first: float = 0.0  # monotonic


# Keep old name for any residual imports
FinalTranscript = TranscriptEvent


class _RecognizeStream:
    _ids = 0

    def __init__(self, loop: asyncio.AbstractEventLoop, owner: "LangStream", primary: str, use_alts: bool):
        _RecognizeStream._ids += 1
        self.id = _RecognizeStream._ids
        self.started_at = time.monotonic()
        self._loop = loop
        self._owner = owner
        self._primary = primary
        self._use_alts = use_alts
        self._audio: queue.Queue[bytes | None] = queue.Queue()
        self._closed = False
        self.finished = False
        self.audio_seconds = 0.0
        self._thread = threading.Thread(target=self._run, name=f"stt-{primary}-{self.id}", daemon=True)
        self._thread.start()
        log.info("STT stream #%d opened (%s, alts=%s)", self.id, primary, use_alts)

    @property
    def age(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def usable(self) -> bool:
        return not self._closed and not self.finished

    def feed(self, chunk: bytes) -> None:
        if self.usable:
            self._audio.put(chunk)
            self.audio_seconds += len(chunk) / (2 * config.SAMPLE_RATE_HZ)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._audio.put(None)

    def _requests(self):
        while True:
            chunk = self._audio.get()
            if chunk is None:
                return
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    def _run(self) -> None:
        try:
            responses = get_speech_client().streaming_recognize(
                config=_build_config(self._primary, self._use_alts),
                requests=self._requests(),
            )
            first_at = 0.0
            for response in responses:
                interim_parts: list[str] = []
                interim_first = None
                for result in response.results:
                    if not result.alternatives:
                        continue
                    alt = result.alternatives[0]
                    text = (alt.transcript or "").strip()
                    if not text:
                        continue
                    if not first_at:
                        first_at = time.monotonic()
                    if not result.is_final:
                        # Google splits one interim into a stable head plus
                        # unstable tail results; show them as one line.
                        interim_parts.append(text)
                        interim_first = interim_first or result
                        continue
                    words = [
                        {
                            "word": w.word,
                            "start": _duration_s(w.start_time),
                            "end": _duration_s(w.end_time),
                            "conf": float(getattr(w, "confidence", 0) or 0),
                        }
                        for w in (getattr(alt, "words", None) or [])
                    ]
                    self._emit(TranscriptEvent(
                        text=text,
                        language_code=result.language_code or self._primary,
                        is_final=True,
                        confidence=float(getattr(alt, "confidence", 0) or 0),
                        words=words,
                        stream_lang=self._primary,
                        t_google_first=first_at,
                    ))
                if interim_parts:
                    self._emit(TranscriptEvent(
                        text=" ".join(interim_parts),
                        language_code=interim_first.language_code or self._primary,
                        is_final=False,
                        stability=float(getattr(interim_first, "stability", 0) or 0),
                        stream_lang=self._primary,
                        t_google_first=first_at,
                    ))
            log.info("STT stream #%d ended after %.0fs (%.1fs audio)", self.id, self.age, self.audio_seconds)
        except Exception as exc:
            log.warning("STT stream #%d error after %.0fs: %s", self.id, self.age, exc)
            self._loop.call_soon_threadsafe(self._owner._on_error, self, str(exc))
        finally:
            self.finished = True
            self._closed = True

    def _emit(self, event: TranscriptEvent) -> None:
        self._loop.call_soon_threadsafe(self._owner._on_result, self, event)


class LangStream:
    """One language's continuous recogniser with rotation + local endpointing."""

    def __init__(self, language: str, use_alternatives: bool = False) -> None:
        self.language = language
        self.use_alternatives = use_alternatives
        self._loop = asyncio.get_running_loop()
        self._current: _RecognizeStream | None = None
        self._closed = False
        self.events: asyncio.Queue[TranscriptEvent] = asyncio.Queue()
        self.errors: asyncio.Queue[str] = asyncio.Queue()
        self._on_event = None  # optional fan-in callback(event)
        self._on_error_cb = None
        self._last_error_at = 0.0
        self._failures = 0
        self._silence_s = 0.0
        self._speech_s = 0.0
        self._utterance_s = 0.0
        self.total_audio_s = 0.0

    def open(self) -> None:
        if self._closed:
            return
        self.total_audio_s = 0.0
        if self._current is None or not self._current.usable:
            self._rotate()

    def feed(self, pcm: bytes) -> None:
        if self._closed:
            return
        stream = self._current
        if stream is None or not stream.usable:
            backoff = min(10, 2 ** max(0, self._failures - 1))
            if time.monotonic() - self._last_error_at < backoff:
                return
            stream = self._rotate()
        elif stream.age >= config.HARD_ROTATE_S:
            stream = self._rotate()
        stream.feed(pcm)
        self.total_audio_s += len(pcm) / (2 * config.SAMPLE_RATE_HZ)
        if self._endpoint(pcm):
            self._rotate()

    def close(self) -> None:
        self._closed = True
        if self._current:
            self.total_audio_s = self._current.audio_seconds  # last stream accounting elsewhere
            self._current.close()
            self._current = None

    def half_close(self) -> None:
        """End current Google stream (finalize) without marking session closed."""
        if self._current:
            self._current.close()
            self._current = None
        self._speech_s = self._silence_s = self._utterance_s = 0.0

    def _rotate(self) -> _RecognizeStream:
        old = self._current
        self._current = _RecognizeStream(self._loop, self, self.language, self.use_alternatives)
        self._speech_s = self._silence_s = self._utterance_s = 0.0
        if old:
            old.close()
        return self._current

    def _endpoint(self, pcm: bytes) -> bool:
        import numpy as np
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return False
        duration = samples.size / config.SAMPLE_RATE_HZ
        rms = float((samples * samples).mean() ** 0.5)
        level = 20 * np.log10(rms / 32768) if rms > 0 else -120.0
        speaking = level > -45
        if speaking:
            self._speech_s += duration
            self._silence_s = 0.0
        else:
            self._silence_s += duration
        if self._speech_s > 0:
            self._utterance_s += duration
        if self._speech_s < 0.25:
            return False
        silence_need = config.ENDPOINT_SILENCE_MS / 1000
        return (
            self._silence_s >= silence_need
            or (self._utterance_s >= config.MAX_UTTERANCE_S and self._silence_s >= 0.25)
            or self._utterance_s >= 2 * config.MAX_UTTERANCE_S
        )

    def _on_result(self, stream: _RecognizeStream, event: TranscriptEvent) -> None:
        if self._closed:
            return
        self.events.put_nowait(event)
        if self._on_event:
            self._on_event(event)
        if event.is_final and stream is self._current:
            if stream.age >= config.SOFT_ROTATE_S:
                self._rotate()
            elif self._silence_s > 0:
                self._speech_s = self._silence_s = self._utterance_s = 0.0

    def _on_error(self, stream: _RecognizeStream, message: str) -> None:
        if self._closed or stream is not self._current:
            return
        if stream.age > 30:
            self._failures = 0
        self._failures += 1
        self._last_error_at = time.monotonic()
        self._current = None
        self.errors.put_nowait(message)
        if self._on_error_cb:
            self._on_error_cb(message)


class MultiLangRecognizer:
    """
    Fans gated PCM to one or more LangStreams and merges via Arbiter.
    Streams are opened/closed by the session gate (not on every chunk).
    """

    def __init__(self, strategy: int | None = None, scout_lang: str | None = None) -> None:
        self.strategy = config.ARBITER_STRATEGY if strategy is None else strategy
        self.arbiter = Arbiter(self.strategy, preferred=scout_lang or config.PRIMARY_LANGUAGE)
        self.results: asyncio.Queue[ArbiterResult] = asyncio.Queue()
        self.errors: asyncio.Queue[str] = asyncio.Queue()
        self.debug: dict = {}
        self._open = False
        self._closed = False
        self._task: asyncio.Task | None = None

        self._inbox: asyncio.Queue[TranscriptEvent | str] = asyncio.Queue()
        if self.strategy == 0:
            lang = scout_lang or config.PRIMARY_LANGUAGE
            self.streams = [LangStream(lang, use_alternatives=True)]
        else:
            langs = list(config.PARALLEL_LANGUAGES)
            self.streams = [LangStream(lang, use_alternatives=False) for lang in langs]

        for s in self.streams:
            s._on_event = lambda ev: self._inbox.put_nowait(ev)
            s._on_error_cb = lambda msg: self._inbox.put_nowait(msg)

        self._latest: dict[str, StreamHypothesis] = {}

    def open_streams(self) -> None:
        if self._closed:
            return
        for s in self.streams:
            s._closed = False
            s.open()
        self._open = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._merge_loop(), name="arbiter-merge")

    def close_streams(self) -> None:
        """Half-close Google streams (finalize) but keep merge loop for finals."""
        for s in self.streams:
            s.half_close()
        self._open = False

    def feed(self, pcm: bytes) -> None:
        if not self._open or self._closed:
            return
        for s in self.streams:
            s.feed(pcm)

    def close(self) -> None:
        self._closed = True
        self._open = False
        for s in self.streams:
            s.close()
        if self._task:
            self._task.cancel()

    def set_language(self, lang: str) -> None:
        """Switch the speaker language mid-session; takes effect on the next utterance."""
        self.arbiter.set_preferred(lang)
        if self.strategy == 0:
            stream = self.streams[0]
            if stream.language != lang:
                stream.language = lang
                # Finalise the in-flight utterance; the next feed/open
                # starts a Google stream configured for the new language.
                stream.half_close()
        log.info("Speaker language -> %s (strategy %d)", lang, self.strategy)

    def audio_seconds_by_lang(self) -> dict[str, float]:
        return {s.language: s.total_audio_s for s in self.streams}

    def _flush_finals(self) -> None:
        pending, self._pending = self._pending, {}
        self._deadline = None
        chosen = self.arbiter.choose(list(pending.values()))
        if chosen:
            chosen.is_final = True
            self.debug = chosen.debug
            self.results.put_nowait(chosen)

    async def _merge_loop(self) -> None:
        # Parallel streams finalize the same utterance at slightly different
        # times; collect their finals and emit one arbitrated caption.
        self._pending: dict[str, StreamHypothesis] = {}
        self._deadline: float | None = None
        while not self._closed:
            timeout = None
            if self._deadline is not None:
                timeout = max(0.0, self._deadline - time.monotonic())
            try:
                item = await asyncio.wait_for(self._inbox.get(), timeout)
            except asyncio.TimeoutError:
                self._flush_finals()
                continue
            if isinstance(item, str):
                self.errors.put_nowait(item)
                continue
            event: TranscriptEvent = item
            key = event.stream_lang or event.language_code
            hyp = StreamHypothesis(
                language=event.language_code or event.stream_lang,
                text=event.text,
                is_final=event.is_final,
                confidence=event.confidence,
                stability=event.stability,
                words=event.words,
            )
            if event.is_final:
                self._pending[key] = hyp
                self._latest.pop(key, None)
                if self._deadline is None:
                    self._deadline = time.monotonic() + FINAL_GATHER_S
                if len(self._pending) >= len(self.streams):
                    self._flush_finals()
                continue

            if key in self._pending:
                # That stream is already on the next utterance.
                self._flush_finals()
            self._latest[key] = hyp
            if self._pending:
                continue
            if len(self.streams) > 1 and self.arbiter.preferred_hyp(list(self._latest.values())) is None:
                if any(
                    script_tag(s.language) == script_tag(self.arbiter.preferred or "")
                    and s.language not in self._latest
                    for s in self.streams
                ):
                    continue  # wait for the preferred stream's interim
            chosen = self.arbiter.choose(list(self._latest.values()))
            if chosen:
                chosen.is_final = False
                self.debug = chosen.debug
                self.results.put_nowait(chosen)


# Back-compat alias used by older imports
class STTSession(LangStream):
    def __init__(self, primary_language: str | None = None) -> None:
        super().__init__(primary_language or config.PRIMARY_LANGUAGE, use_alternatives=True)
        self.primary_language = self.language
        self.results = self.events
