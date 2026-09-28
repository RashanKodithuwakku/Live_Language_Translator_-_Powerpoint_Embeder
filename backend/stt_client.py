"""
stt_client.py
─────────────
Google Cloud Speech-to-Text v1 streaming recognition with seamless,
operator-invisible stream rotation.

Threading model
───────────────
The google-cloud-speech `streaming_recognize` helper is a *blocking* gRPC
bidirectional stream: it consumes a request generator and yields responses.
Each stream therefore runs on its own daemon thread:

    event loop ──feed()──► thread-safe audio queue ──► request generator ─┐
                                                                          │ gRPC
    event loop ◄─call_soon_threadsafe── response loop (worker thread) ◄───┘

Nothing Google-related ever blocks the asyncio event loop, so WebSocket
audio ingestion and caption delivery stay responsive at all times.

Stream rotation (the ~305 s server-side limit)
──────────────────────────────────────────────
Google terminates a streaming session after ~305 s. We rotate *before*
that happens, using overlapping streams so no audio is ever dropped:

  1. A NEW stream is opened and from that instant receives all new audio.
  2. The OLD stream is half-closed (its request generator ends). Google
     then flushes any in-flight words as a final result and ends the
     stream naturally — the sentence the speaker was in is not lost.

Rotation timing:
  • Endpoint rotation: the si-LK / ta-LK `default` models are slow to
    decide that a sentence has ended (measured 14-29 s after the speaker
    stopped). A level-based voice-activity detector watches the cleaned
    audio; once the speaker has talked and then paused for
    STT_ENDPOINT_SILENCE_MS, the stream is rotated so Google finalizes the
    sentence right away (~1-2 s). A speaker who never pauses is cut at the
    next short breath after STT_MAX_UTTERANCE_S, or unconditionally at
    twice that.
  • Soft rotation: right after a final result once the stream is older
    than STT_SESSION_RESTART_INTERVAL (default 240 s). Finals coincide with
    natural pauses in speech, so this almost never cuts a sentence.
  • Hard rotation: on the next audio chunk once the stream is older than
    STT_SESSION_RESTART_INTERVAL + 40 s (capped at 290 s), in case the
    speaker talks for a long time without pausing.
  • Error recovery: if a stream dies (network blip, audio timeout, quota),
    the next audio chunk transparently opens a fresh stream. Repeated
    immediate failures back off exponentially up to 10 s.

Model choice
────────────
Per Google's v1 language-support table, si-LK and ta-LK are only served by
the `default` and `command_and_search` models (NOT `latest_long`). We use
`default` (continuous speech) unless STT_MODEL overrides it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import queue
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np
from google.cloud import speech

log = logging.getLogger("stt")

SAMPLE_RATE_HZ = 16_000

PRIMARY_LANGUAGE = os.getenv("STT_PRIMARY_LANGUAGE", "si-LK")
ALTERNATIVE_LANGUAGES = [
    code.strip()
    for code in os.getenv("STT_ALTERNATIVE_LANGUAGES", "ta-LK,en-US").split(",")
    if code.strip()
]
SUPPORTED_LANGUAGES = [PRIMARY_LANGUAGE] + [c for c in ALTERNATIVE_LANGUAGES if c != PRIMARY_LANGUAGE]
STT_MODEL = os.getenv("STT_MODEL", "default")
AUTO_PUNCTUATION = os.getenv("STT_AUTO_PUNCTUATION", "true").lower() == "true"

SOFT_ROTATE_S = int(os.getenv("STT_SESSION_RESTART_INTERVAL", "240"))
HARD_ROTATE_S = min(SOFT_ROTATE_S + 40, 290)
MAX_RETRY_BACKOFF_S = 10
HEALTHY_STREAM_S = 30

ENDPOINT_SILENCE_S = int(os.getenv("STT_ENDPOINT_SILENCE_MS", "700")) / 1000
MAX_UTTERANCE_S = float(os.getenv("STT_MAX_UTTERANCE_S", "15"))
BREATH_SILENCE_S = 0.25
MIN_SPEECH_S = 0.3
# Speech must sit this far above the rolling noise floor (and above an
# absolute floor, so digital silence with a -inf floor can't trigger it).
VAD_MARGIN_DB = 12.0
VAD_ABSOLUTE_MIN_DBFS = -55.0
NOISE_FLOOR_WINDOW_S = 10.0

_speech_client: speech.SpeechClient | None = None
_client_lock = threading.Lock()


def get_speech_client() -> speech.SpeechClient:
    """Process-wide client. Credentials come from GOOGLE_APPLICATION_CREDENTIALS."""
    global _speech_client
    with _client_lock:
        if _speech_client is None:
            _speech_client = speech.SpeechClient()
        return _speech_client


def _build_streaming_config(primary: str) -> speech.StreamingRecognitionConfig:
    return speech.StreamingRecognitionConfig(
        config=speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=SAMPLE_RATE_HZ,
            audio_channel_count=1,
            language_code=primary,
            alternative_language_codes=[c for c in SUPPORTED_LANGUAGES if c != primary],
            enable_automatic_punctuation=AUTO_PUNCTUATION,
            model=STT_MODEL,
        ),
        # Interim results keep Google's endpointing responsive; they are
        # consumed here and never forwarded to the audience.
        interim_results=True,
        single_utterance=False,
    )


@dataclass(frozen=True)
class FinalTranscript:
    text: str
    language_code: str


class _RecognizeStream:
    """One Google streaming session running on a dedicated worker thread."""

    _ids = 0

    def __init__(self, loop: asyncio.AbstractEventLoop, owner: "STTSession"):
        _RecognizeStream._ids += 1
        self.id = _RecognizeStream._ids
        self.started_at = time.monotonic()
        self._loop = loop
        self._owner = owner
        self._audio: queue.Queue[bytes | None] = queue.Queue()
        self._closed = False
        self.finished = False
        self._thread = threading.Thread(
            target=self._run, name=f"stt-stream-{self.id}", daemon=True
        )
        self._thread.start()
        log.info("STT stream #%d opened", self.id)

    @property
    def age(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def usable(self) -> bool:
        return not self._closed and not self.finished

    def feed(self, chunk: bytes) -> None:
        if self.usable:
            self._audio.put(chunk)

    def close(self) -> None:
        """Half-close: Google flushes pending words as a final, then ends."""
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
                config=_build_streaming_config(self._owner.primary_language),
                requests=self._requests(),
            )
            for response in responses:
                for result in response.results:
                    if not result.is_final or not result.alternatives:
                        continue
                    text = result.alternatives[0].transcript.strip()
                    if not text:
                        continue
                    final = FinalTranscript(
                        text=text,
                        language_code=result.language_code or self._owner.primary_language,
                    )
                    self._loop.call_soon_threadsafe(self._owner._on_final, self, final)
            log.info("STT stream #%d ended after %.0fs", self.id, self.age)
        except Exception as exc:  # gRPC errors surface here
            log.warning("STT stream #%d error after %.0fs: %s", self.id, self.age, exc)
            self._loop.call_soon_threadsafe(self._owner._on_stream_error, self, str(exc))
        finally:
            self.finished = True
            self._closed = True


class STTSession:
    """
    Continuous recognition for one translation session.

    Usage (from the event loop):
        stt = STTSession("si-LK")      # primary language; others are alternatives
        stt.feed(pcm_bytes)            # every ~100 ms
        final = await stt.results.get()
        stt.close()
    """

    def __init__(self, primary_language: str | None = None) -> None:
        self.primary_language = (
            primary_language if primary_language in SUPPORTED_LANGUAGES else PRIMARY_LANGUAGE
        )
        self._loop = asyncio.get_running_loop()
        self._current: _RecognizeStream | None = None
        self._closed = False
        self.results: asyncio.Queue[FinalTranscript] = asyncio.Queue()
        self.errors: asyncio.Queue[str] = asyncio.Queue()
        self._last_error_at = 0.0
        self._consecutive_failures = 0
        self._levels: deque[float] = deque()
        self._reset_utterance()

    def feed(self, pcm: bytes) -> None:
        if self._closed:
            return
        stream = self._current
        if stream is None or not stream.usable:
            # Exponential back-off (1 s → 10 s) so a persistent error (bad
            # credentials, quota) doesn't open a gRPC stream every 100 ms.
            backoff = min(MAX_RETRY_BACKOFF_S, 2 ** max(0, self._consecutive_failures - 1))
            if time.monotonic() - self._last_error_at < backoff:
                return
            stream = self._rotate()
        elif stream.age >= HARD_ROTATE_S:
            stream = self._rotate()
        stream.feed(pcm)
        if self._update_vad(pcm):
            self._rotate()

    # ── voice-activity endpointing ──────────────────────────────────────────
    def _reset_utterance(self) -> None:
        self._speech_s = 0.0
        self._silence_s = 0.0
        self._utterance_s = 0.0

    def _update_vad(self, pcm: bytes) -> bool:
        """Track speech/pause for this chunk; True = end the utterance now."""
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return False
        duration = samples.size / SAMPLE_RATE_HZ
        rms = float(np.sqrt(np.mean(samples * samples)))
        level = 20 * np.log10(rms / 32768) if rms > 0 else -120.0

        self._levels.append(level)
        while len(self._levels) * duration > NOISE_FLOOR_WINDOW_S:
            self._levels.popleft()
        threshold = max(min(self._levels) + VAD_MARGIN_DB, VAD_ABSOLUTE_MIN_DBFS)

        if level > threshold:
            self._speech_s += duration
            self._silence_s = 0.0
        else:
            self._silence_s += duration
        if self._speech_s > 0:
            self._utterance_s += duration
        if self._speech_s < MIN_SPEECH_S:
            if self._silence_s >= ENDPOINT_SILENCE_S:
                self._reset_utterance()  # a click or cough, not speech
            return False

        return (
            self._silence_s >= ENDPOINT_SILENCE_S
            or (self._utterance_s >= MAX_UTTERANCE_S and self._silence_s >= BREATH_SILENCE_S)
            or self._utterance_s >= 2 * MAX_UTTERANCE_S
        )

    def close(self) -> None:
        self._closed = True
        if self._current:
            self._current.close()
            self._current = None

    def _rotate(self) -> _RecognizeStream:
        old = self._current
        self._current = _RecognizeStream(self._loop, self)
        self._reset_utterance()
        if old:
            old.close()
        return self._current

    # ── callbacks (run on the event loop via call_soon_threadsafe) ──────────
    def _on_final(self, stream: _RecognizeStream, final: FinalTranscript) -> None:
        if self._closed:
            return
        self.results.put_nowait(final)
        if stream is self._current:
            if stream.age >= SOFT_ROTATE_S:
                self._rotate()
            elif self._silence_s > 0:
                # Google endpointed on its own during this pause.
                self._reset_utterance()

    def _on_stream_error(self, stream: _RecognizeStream, message: str) -> None:
        if self._closed or stream is not self._current:
            return
        if stream.age > HEALTHY_STREAM_S:
            self._consecutive_failures = 0
        self._consecutive_failures += 1
        self._last_error_at = time.monotonic()
        self._current = None
        self.errors.put_nowait(message)
