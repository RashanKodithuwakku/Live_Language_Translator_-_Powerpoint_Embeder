"""
Translation WebSocket session.

Audio path: PCM → preprocess → VAD gate → (open/close STT) → arbiter → translate → UI.

Profiles:
  ECO   — Strategy 0 scout, finals-only translation, hard budget stop
  EVENT — parallel recognisers, progressive translation, budget warn only
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque

from fastapi import WebSocket, WebSocketDisconnect

import config
from audio_processor import AudioProcessor
from stt_client import MultiLangRecognizer
from translation_client import translate_to_sinhala_and_tamil
from usage_ledger import ledger
from vad_gate import SpeechGate

log = logging.getLogger("ws")

ERROR_REPEAT_SUPPRESS_S = 15.0
AUDIO_QUEUE_MAX = 5  # ~500 ms of 100 ms chunks
SPEAKER_LANGUAGES = {"si-LK", "ta-LK", "ta-IN", "en-US", "en-GB"}


class LatencyTracker:
    def __init__(self) -> None:
        self.samples: dict[str, deque[float]] = {
            k: deque(maxlen=60)
            for k in ("backend_recv_ms", "google_interim_ms", "final_ms", "translate_ms", "e2e_ms")
        }
        self.last: dict = {}

    def add(self, stage: str, ms: float) -> None:
        if stage in self.samples:
            self.samples[stage].append(ms)
        self.last[stage] = round(ms, 1)

    def snapshot(self) -> dict:
        out = {"last": dict(self.last)}
        for k, vals in self.samples.items():
            if not vals:
                continue
            s = sorted(vals)
            out[k] = {
                "p50": round(s[len(s) // 2], 1),
                "p95": round(s[max(0, int(len(s) * 0.95) - 1)], 1),
                "n": len(s),
            }
        return out


class TranslationSession:
    def __init__(
        self,
        websocket: WebSocket,
        send_lock: asyncio.Lock,
        language: str | None,
        profile: str | None = None,
    ):
        self._ws = websocket
        self._send_lock = send_lock
        self._profile = (profile or config.PROFILE).lower()
        if self._profile not in {"eco", "event"}:
            self._profile = "eco"
        self._scout_lang = language
        if self._profile == "eco":
            strategy = 0
        else:
            strategy = config.ARBITER_STRATEGY if config.ARBITER_STRATEGY >= 1 else 1
            if strategy == 2 and not config.ENABLE_STRATEGY_2:
                strategy = 1

        self._processor = AudioProcessor()
        self._gate = SpeechGate()
        self._stt = MultiLangRecognizer(strategy=strategy, scout_lang=language)
        self._latency = LatencyTracker()
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._streams_open = False
        self._last_error = ("", 0.0)
        self._audio_q: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=AUDIO_QUEUE_MAX)
        self._last_speech_at = time.monotonic()
        self._idle_paused = False
        self._noise_open_since: float | None = None
        self._words_seen = False
        self._last_original = ""
        self._last_si = ""
        self._last_ta = ""
        self._translate_seq = 0
        self._inflight_si = False
        self._inflight_ta = False
        self._last_prog_at = 0.0
        self._t_utterance_start = 0.0
        self._budget_blocked = False

    async def start(self) -> None:
        self._running = True
        ok, warn = ledger.allow_google()
        if not ok:
            self._budget_blocked = True
            await self._send({"type": "error", "message": warn})
        elif warn:
            await self._send({"type": "status", "message": warn})

        self._tasks = [
            asyncio.create_task(self._audio_worker(), name="audio-worker"),
            asyncio.create_task(self._deliver(), name="deliver"),
            asyncio.create_task(self._forward_errors(), name="stt-errors"),
            asyncio.create_task(self._idle_watch(), name="idle-watch"),
        ]
        await self._send({
            "type": "status",
            "message": (
                f"Session started · profile={self._profile} · strategy={self._stt.strategy}"
                + (" · CACHE MODE" if config.is_cache_mode() else "")
            ),
        })
        await self._send_usage()

    async def stop(self, notify: bool = True) -> None:
        if not self._running:
            return
        self._running = False
        await self._audio_q.put(None)
        self._close_streams(record=True)
        self._stt.close()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if notify:
            snap = ledger.snapshot()
            await self._send({
                "type": "status",
                "message": (
                    f"Stopped · today ~${snap['today']['est_usd']:.3f} "
                    f"({snap['today']['stt_seconds']:.0f}s STT, "
                    f"{snap['today']['translate_chars']} chars)"
                ),
            })
            await self._send_usage()

    async def set_language(self, lang: str) -> None:
        if lang == self._scout_lang:
            return
        self._scout_lang = lang
        self._stt.set_language(lang)
        await self._send({"type": "status", "message": f"Speaker language → {lang}"})

    async def push_audio(self, pcm: bytes, t_client: float | None = None) -> None:
        if not self._running:
            return
        # Bounded queue: drop-oldest if backlog > ~500 ms
        if self._audio_q.full():
            try:
                self._audio_q.get_nowait()
                log.warning("Audio backlog >500 ms — dropped oldest chunk")
            except asyncio.QueueEmpty:
                pass
        try:
            self._audio_q.put_nowait(pcm)
        except asyncio.QueueFull:
            pass

    async def _audio_worker(self) -> None:
        while True:
            pcm = await self._audio_q.get()
            if pcm is None:
                return
            t0 = time.monotonic()
            cleaned = await asyncio.to_thread(self._processor.process, pcm)
            self._latency.add("backend_recv_ms", (time.monotonic() - t0) * 1000)

            decision = self._gate.process(cleaned)

            if self._idle_paused:
                if decision.just_started or decision.frame_is_speech:
                    self._idle_paused = False
                    await self._send({"type": "status", "message": "Resumed on speech"})
                else:
                    continue

            if self._budget_blocked:
                continue

            if decision.just_started:
                ok, warn = ledger.allow_google()
                if not ok:
                    self._budget_blocked = True
                    await self._send({"type": "error", "message": warn or "Budget exhausted"})
                    continue
                if warn:
                    await self._send({"type": "status", "message": warn})
                self._open_streams()
                self._t_utterance_start = time.monotonic()
                self._words_seen = False
                self._noise_open_since = time.monotonic()
                for chunk in decision.preroll:
                    self._stt.feed(chunk)

            if decision.speech_active and self._streams_open and not self._budget_blocked:
                self._last_speech_at = time.monotonic()
                if not decision.just_started:
                    self._stt.feed(cleaned)

            if decision.just_ended and self._streams_open:
                self._close_streams(record=True)

            # Noise-burn: open long with no words
            if (
                self._streams_open
                and self._noise_open_since
                and not self._words_seen
                and time.monotonic() - self._noise_open_since > config.NOISE_BURN_SECONDS
            ):
                log.warning("Noise-burn guard: closing streams, raising VAD")
                self._close_streams(record=True)
                self._gate.bump_threshold()
                await self._send({"type": "status", "message": "Noise floor high — VAD tightened"})

    def _open_streams(self) -> None:
        if self._streams_open or self._budget_blocked:
            return
        if config.is_cache_mode():
            self._streams_open = True
            return
        self._stt.open_streams()
        self._streams_open = True

    def _close_streams(self, record: bool = False) -> None:
        if not self._streams_open:
            return
        by_lang = self._stt.audio_seconds_by_lang()
        self._stt.close_streams()
        self._streams_open = False
        self._noise_open_since = None
        if record and not config.is_cache_mode():
            for lang, secs in by_lang.items():
                ledger.record_stt(secs, lang, self._profile)

    async def _idle_watch(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            idle = time.monotonic() - self._last_speech_at
            if self._streams_open and idle >= config.IDLE_CLOSE_SECONDS:
                self._close_streams(record=True)
            if not self._idle_paused and idle >= config.IDLE_PAUSE_SECONDS:
                self._idle_paused = True
                self._close_streams(record=True)
                await self._send({"type": "status", "message": "Idle — resumes on speech"})

    async def _deliver(self) -> None:
        while True:
            result = await self._stt.results.get()
            self._words_seen = True
            original = result.text
            # Never shrink displayed original on interim
            if not result.is_final and len(original) < len(self._last_original) and self._last_original.startswith(original):
                original = self._last_original
            self._last_original = original

            now = time.monotonic()
            if self._t_utterance_start:
                stage = "final_ms" if result.is_final else "google_interim_ms"
                self._latency.add(stage, (now - self._t_utterance_start) * 1000)

            progressive = self._profile == "event" and config.TRANSLATE_PROGRESSIVE and not result.is_final
            finals_only = self._profile == "eco" or not config.TRANSLATE_PROGRESSIVE

            if result.is_final or (progressive and self._should_prog_translate(original)):
                t_tr = time.monotonic()
                self._translate_seq += 1
                seq = self._translate_seq
                si, ta = await translate_to_sinhala_and_tamil(original, result.language)
                if seq != self._translate_seq and not result.is_final:
                    continue  # stale progressive
                self._latency.add("translate_ms", (time.monotonic() - t_tr) * 1000)
                if si:
                    self._last_si = si
                if ta:
                    self._last_ta = ta
            elif finals_only and not result.is_final:
                # ECO interim: show original only
                await self._send({
                    "type": "translation",
                    "sinhala": self._last_si,
                    "tamil": self._last_ta,
                    "original": original,
                    "isFinal": False,
                    "lang": result.language,
                    "latency": self._latency.snapshot(),
                    "debug": result.debug if getattr(result, "debug", None) else self._stt.debug,
                })
                continue

            if self._t_utterance_start:
                self._latency.add("e2e_ms", (time.monotonic() - self._t_utterance_start) * 1000)

            await self._send({
                "type": "translation",
                "sinhala": self._last_si,
                "tamil": self._last_ta,
                "original": original,
                "isFinal": result.is_final,
                "lang": result.language,
                "latency": self._latency.snapshot(),
                "debug": result.debug if getattr(result, "debug", None) else self._stt.debug,
            })
            if result.is_final:
                self._last_original = ""
                await self._send_usage()

    def _should_prog_translate(self, text: str) -> bool:
        now = time.monotonic()
        if now - self._last_prog_at < config.TRANSLATE_MIN_INTERVAL_MS / 1000:
            return False
        words = text.split()
        prev = self._last_si  # weak signal; use word growth vs last original translated
        if not hasattr(self, "_last_prog_words"):
            self._last_prog_words = 0
        if len(words) - self._last_prog_words >= 2 or (prev and len(words) > self._last_prog_words):
            self._last_prog_words = len(words)
            self._last_prog_at = now
            return True
        return False

    async def _forward_errors(self) -> None:
        while True:
            message = await self._stt.errors.get()
            await self._send_error(f"Speech recognition interrupted: {message}")

    async def _send_error(self, message: str) -> None:
        last_message, last_at = self._last_error
        now = time.monotonic()
        if message == last_message and now - last_at < ERROR_REPEAT_SUPPRESS_S:
            return
        self._last_error = (message, now)
        await self._send({"type": "error", "message": message})

    async def _send_usage(self) -> None:
        await self._send({"type": "usage", "usage": ledger.snapshot()})

    async def _send(self, payload: dict) -> None:
        try:
            async with self._send_lock:
                await self._ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            pass


async def handle_translation_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    language = websocket.query_params.get("lang")
    profile = websocket.query_params.get("profile") or config.PROFILE
    log.info(
        "Client connected: %s lang=%s profile=%s mode=%s",
        websocket.client, language, profile, config.MODE,
    )
    send_lock = asyncio.Lock()
    session: TranslationSession | None = TranslationSession(websocket, send_lock, language, profile)
    await session.start()

    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            data = message.get("bytes")
            if data:
                if session:
                    await session.push_audio(data)
                continue

            text = (message.get("text") or "").strip()
            upper = text.upper()
            if upper == "STOP" and session:
                await session.stop()
                session = None
            elif upper == "START" or upper.startswith("START|"):
                # START|eco or START|event
                parts = text.split("|")
                new_profile = parts[1].strip().lower() if len(parts) > 1 else profile
                if session:
                    await session.stop(notify=False)
                session = TranslationSession(websocket, send_lock, language, new_profile)
                await session.start()
            elif upper.startswith("LANG|"):
                new_lang = text.split("|", 1)[1].strip()
                if new_lang in SPEAKER_LANGUAGES:
                    language = new_lang
                    if session:
                        await session.set_language(new_lang)
                else:
                    log.warning("Ignoring unknown speaker language %r", new_lang)
            elif upper == "USAGE":
                if session:
                    await session._send_usage()
            elif upper.startswith("OVERRIDE"):
                ledger.activate_override(4.0)
                if session:
                    session._budget_blocked = False
                    await session._send({"type": "status", "message": "Budget override active (4 h)"})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("WebSocket handler error")
    finally:
        if session:
            await session.stop(notify=False)
        log.info("Client disconnected: %s", websocket.client)
