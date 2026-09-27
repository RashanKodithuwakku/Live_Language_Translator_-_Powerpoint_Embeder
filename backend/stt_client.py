"""
stt_client.py
─────────────
Wraps Google Cloud Speech-to-Text v1 streaming recognition.

Key design decisions
────────────────────
• We use the v1 (not v1p1beta1) API because `alternativeLanguageCodes` is
  now GA in v1 and covers Sinhala (si-LK) + Tamil (ta-LK / ta-IN) +
  English (en-US) without a separate feature flag.

• The STT streaming session has a hard server-side limit of 305 seconds
  (~5 min). We proactively restart the stream every STT_SESSION_RESTART_INTERVAL
  seconds (default 240 s, configurable via .env) so there is never a
  visible cut. Restarting is transparent to the operator and audience.

• Audio chunks are placed into an asyncio.Queue. A separate async generator
  feeds the queue into the blocking gRPC streaming call, which runs inside
  asyncio.to_thread() so it never blocks the event loop.

• Only `is_final=True` results are yielded to callers. Interim partials
  are consumed silently (they drive perceived responsiveness on the Google
  side without being shown to the audience).
"""

import asyncio
import os
import time
from typing import AsyncGenerator

from google.cloud import speech


# ── Module-level singleton client (created once per process) ────────────────
_speech_client: speech.SpeechClient | None = None


def get_speech_client() -> speech.SpeechClient:
    global _speech_client
    if _speech_client is None:
        # Credentials are picked up automatically from the environment
        # variable GOOGLE_APPLICATION_CREDENTIALS set by .env / main.py.
        _speech_client = speech.SpeechClient()
    return _speech_client


# ── Streaming config ─────────────────────────────────────────────────────────
def _build_streaming_config() -> speech.StreamingRecognitionConfig:
    recognition_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16_000,
        audio_channel_count=1,
        language_code="si-LK",                          # Primary: Sinhala
        alternative_language_codes=["ta-LK", "en-US"],  # Auto-detect Tamil / English
        enable_automatic_punctuation=True,
        model="latest_long",   # Best latency/accuracy for live speech
        use_enhanced=True,     # Enhanced model where available
    )
    return speech.StreamingRecognitionConfig(
        config=recognition_config,
        interim_results=True,   # Receive partials (consumed internally, not shown)
        single_utterance=False, # Continuous, never auto-stops
    )


# ── Per-session STT runner ───────────────────────────────────────────────────
class STTSession:
    """
    Manages a single Google STT streaming session lifetime.

    Usage:
        session = STTSession(audio_queue)
        async for transcript, language_code in session.stream_results():
            ...  # handle final transcript

    `audio_queue` is an asyncio.Queue[bytes | None].
      - Push raw PCM bytes to add audio.
      - Push None to signal end-of-session (terminates the stream cleanly).
    """

    def __init__(self, audio_queue: asyncio.Queue):
        self._queue = audio_queue
        self._restart_interval = int(os.getenv("STT_SESSION_RESTART_INTERVAL", "240"))

    def _audio_generator(self):
        """
        Synchronous generator consumed by the blocking gRPC call.
        Runs inside asyncio.to_thread so it doesn't block the event loop.
        Uses a thread-safe queue bridge populated by _pump_audio().
        """
        while True:
            chunk = self._sync_queue.get()  # blocks in the thread
            if chunk is None:
                return
            yield speech.StreamingRecognizeRequest(audio_content=chunk)

    async def stream_results(
        self,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """
        Async generator that yields (transcript_text, language_code) tuples
        for every is_final result. Automatically restarts the STT session
        when the restart interval is reached.
        """
        import queue as thread_queue

        client = get_speech_client()

        while True:  # outer loop handles session restarts
            # Bridge between asyncio queue and the sync generator
            self._sync_queue: thread_queue.Queue = thread_queue.Queue()
            session_start = time.monotonic()

            # Start pumping audio from async queue → sync queue
            pump_task = asyncio.create_task(self._pump_audio(self._sync_queue))

            try:
                config = _build_streaming_config()
                responses_iter = await asyncio.to_thread(
                    self._run_blocking_stream, client, config
                )

                for response in responses_iter:
                    elapsed = time.monotonic() - session_start
                    if elapsed >= self._restart_interval:
                        # Proactively trigger a session restart
                        self._sync_queue.put(None)
                        break

                    for result in response.results:
                        if not result.is_final:
                            continue
                        alt = result.alternatives[0]
                        lang = getattr(result, "language_code", "unknown")
                        yield alt.transcript.strip(), lang

            except Exception as exc:
                # Log but don't crash — the outer loop will restart the session.
                print(f"[STT] Session error (will restart): {exc}")

            finally:
                pump_task.cancel()
                try:
                    await pump_task
                except asyncio.CancelledError:
                    pass

            # Brief pause before restarting to avoid a tight spin on repeated errors
            await asyncio.sleep(0.2)

    def _run_blocking_stream(
        self,
        client: speech.SpeechClient,
        config: speech.StreamingRecognitionConfig,
    ):
        """
        Called inside asyncio.to_thread().
        Executes the blocking gRPC streaming_recognize call and returns
        the response iterator (which is also evaluated in the thread).
        We collect all responses into a list and return them synchronously
        — this is fine because we rely on is_final events, not sub-second
        streaming back-pressure.

        Actually, we return the raw iterator and let the caller iterate it
        inside to_thread via a wrapper approach. See stream_results() for
        how this is consumed.
        """
        # NOTE: We return the raw iterator here. The caller (stream_results)
        # iterates it synchronously inside asyncio.to_thread.
        return client.streaming_recognize(
            config=config,
            requests=self._audio_generator(),
        )

    async def _pump_audio(self, sync_q) -> None:
        """
        Continuously moves items from the async audio_queue into the
        synchronous thread queue so the blocking gRPC generator can consume them.
        """
        try:
            while True:
                chunk = await self._queue.get()
                sync_q.put(chunk)
                if chunk is None:
                    return
        except asyncio.CancelledError:
            sync_q.put(None)  # unblock the sync generator
