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
import wave
from collections import deque

import numpy as np
from fastapi import WebSocket, WebSocketDisconnect

import config
from audio_processor import AudioProcessor
from content_filter import FilterResult, content_filter
from stt_client import MultiLangRecognizer
from llm_context import clean_sentence
from translation_client import translate_mixed, translate_to_sinhala_and_tamil
from usage_ledger import ledger
from vad_gate import SpeechGate

log = logging.getLogger("ws")

ERROR_REPEAT_SUPPRESS_S = 15.0
AUDIO_QUEUE_MAX = 5  # ~500 ms of 100 ms chunks
STOP_DRAIN_S = 2.5
QUIET_DBFS = -58.0
QUIET_WARN_S = 6.0
NO_SPEECH_MIN_DBFS = -55.0
NO_SPEECH_WARN_S = 10.0
# First seconds of each session's input, kept locally (gitignored) so a
# failed mixer setup can be diagnosed from the real signal.
DIAG_RECORD_BYTES = 20 * 2 * 16000
DIAG_PATH = config.CACHE_DIR / "last_input.wav"
SPEAKER_LANGUAGES = {"si-LK", "ta-LK", "ta-IN", "en-US", "en-GB"}


class LatencyTracker:
    def __init__(self) -> None:
        self.samples: dict[str, deque[float]] = {
            k: deque(maxlen=60)
            for k in ("backend_recv_ms", "google_interim_ms", "final_ms", "translate_ms", "llm_ms", "e2e_ms")
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
        self._last_en = ""
        self._context: deque[str] = deque(maxlen=config.LLM_CONTEXT_SENTENCES)
        self._translate_seq = 0
        self._inflight_si = False
        self._inflight_ta = False
        self._last_prog_at = 0.0
        self._t_utterance_start = 0.0
        self._budget_blocked = False
        self._delivering = False
        self._chunks = 0
        self._level_sum = 0.0
        self._quiet_s = 0.0
        self._quiet_warned = False
        self._interims = 0
        self._finals = 0
        self._no_speech_s = 0.0
        self._no_speech_warned = False
        self._blocked = 0
        self._utterance_tainted = False
        self._diag = bytearray()
        self._diag_bytes = 0

    async def start(self) -> None:
        self._running = True
        ok, warn = ledger.allow_google()
        if not ok:
            self._budget_blocked = True
            await self._send({"type": "error", "message": warn})
        elif warn:
            await self._send({"type": "status", "message": warn})
        if config.FILTER_ENABLED and not content_filter.loaded:
            await self._send({
                "type": "error",
                "message": "Content filter list (blocklist.json) failed to load — captions are NOT filtered.",
            })

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
        if notify:
            # Operator Stop mid-sentence: let Google finalise and translate
            # the words already spoken instead of discarding them.
            await self._stt.drain(STOP_DRAIN_S)
            deadline = time.monotonic() + STOP_DRAIN_S
            while time.monotonic() < deadline and (self._delivering or not self._stt.results.empty()):
                await asyncio.sleep(0.05)
        self._stt.close()
        log.info(
            "Session summary: %.0fs audio received, avg input %.0f dBFS, speech in %.0f%% of chunks, "
            "%d speech segments, %d interim / %d final captions, %d filtered",
            self._chunks * 0.1,
            (self._level_sum / self._chunks) if self._chunks else -120.0,
            100 * self._gate.speech_frames / max(1, self._chunks),
            self._gate.opens,
            self._interims,
            self._finals,
            self._blocked,
        )
        await asyncio.to_thread(self._save_recording)
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
            level = await self._check_input_level(pcm)
            t0 = time.monotonic()
            cleaned = await asyncio.to_thread(self._processor.process, pcm)
            self._latency.add("backend_recv_ms", (time.monotonic() - t0) * 1000)

            decision = self._gate.process(cleaned)
            await self._check_speech_found(level, decision.speech_active)

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

    async def _check_speech_found(self, level: float, speech_active: bool) -> None:
        if speech_active or level < NO_SPEECH_MIN_DBFS:
            if speech_active:
                self._no_speech_s = 0.0
                self._no_speech_warned = False
            return
        self._no_speech_s += 0.1
        if self._no_speech_s >= NO_SPEECH_WARN_S and not self._no_speech_warned:
            self._no_speech_warned = True
            log.warning("Sound present (%.0f dBFS) for %.0fs but no speech detected", level, self._no_speech_s)
            await self._send({
                "type": "error",
                "message": (
                    "Sound is coming in but no speech is detected. On the mixer, send the "
                    "microphone channel to the USB/main output and raise its level."
                ),
            })

    def _record(self, pcm: bytes) -> None:
        if self._diag_bytes < DIAG_RECORD_BYTES:
            self._diag.extend(pcm[: DIAG_RECORD_BYTES - self._diag_bytes])
            self._diag_bytes = len(self._diag)

    def _save_recording(self) -> None:
        if not self._diag:
            return
        try:
            config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            with wave.open(str(DIAG_PATH), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(config.SAMPLE_RATE_HZ)
                w.writeframes(bytes(self._diag))
            log.info("Saved first %.0fs of input to %s", len(self._diag) / 32000, DIAG_PATH)
        except Exception as exc:
            log.warning("Could not save input recording: %s", exc)

    async def _check_input_level(self, pcm: bytes) -> float:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
        if samples.size == 0:
            return -120.0
        self._record(pcm)
        rms = float(np.sqrt(np.mean(samples * samples)))
        self._chunks += 1
        if rms == 0:
            # Exact zeros = UI paused capture for slide media (a muted
            # device is flagged by the UI meter instead).
            self._level_sum += -120.0
            return -120.0
        level = 20 * np.log10(rms / 32768)
        self._level_sum += level
        if level < QUIET_DBFS:
            self._quiet_s += samples.size / config.SAMPLE_RATE_HZ
        else:
            self._quiet_s = 0.0
            self._quiet_warned = False
        if self._quiet_s >= QUIET_WARN_S and not self._quiet_warned:
            self._quiet_warned = True
            log.warning("Input near-silent for %.0fs (%.0f dBFS)", self._quiet_s, level)
            await self._send({
                "type": "error",
                "message": "No sound from the selected input — check the input device, mute switch, or mixer level.",
            })
        return level

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
            self._delivering = True
            try:
                await self._deliver_one(result)
            finally:
                self._delivering = False

    async def _deliver_one(self, result) -> None:
        self._words_seen = True
        original = result.text
        # Never shrink displayed original on interim
        if not result.is_final and len(original) < len(self._last_original) and self._last_original.startswith(original):
            original = self._last_original
        self._last_original = original

        # Filter before anything is shown or sent to Translate. Once a
        # sentence's preview held a blocked word, keep hiding its previews:
        # Google revises previews back and forth.
        if result.is_final:
            self._utterance_tainted = False
        elif self._utterance_tainted and config.FILTER_ACTION == "drop":
            return
        checked = content_filter.check(original, interim=not result.is_final)
        if checked.blocked:
            if checked.confirmed:
                self._log_blocked("original", checked, result.is_final)
                if not result.is_final:
                    self._utterance_tainted = True
            if checked.dropped:
                if result.is_final:
                    self._last_original = ""
                return
            original = checked.text

        now = time.monotonic()
        if self._t_utterance_start:
            stage = "final_ms" if result.is_final else "google_interim_ms"
            self._latency.add(stage, (now - self._t_utterance_start) * 1000)

        # Finished sentences go to Gemini with the previous five captions
        # before anything new is drawn. Live previews stay off in that mode
        # so slang in a half-sentence never flashes up.
        hold_for_llm = config.LLM_ENABLED and not config.is_cache_mode()
        if hold_for_llm and not result.is_final:
            self._interims += 1
            return

        progressive = (
            not hold_for_llm
            and self._profile == "event"
            and config.TRANSLATE_PROGRESSIVE
            and not result.is_final
        )
        finals_only = self._profile == "eco" or not config.TRANSLATE_PROGRESSIVE

        if result.is_final:
            self._finals += 1
        else:
            self._interims += 1

        english = self._last_en
        if result.is_final or (progressive and self._should_prog_translate(original)):
            t_tr = time.monotonic()
            self._translate_seq += 1
            seq = self._translate_seq
            cleaned = None
            if result.is_final and hold_for_llm:
                cleaned = await clean_sentence(original, result.language, list(self._context))
                self._latency.add("llm_ms", (time.monotonic() - t_tr) * 1000)
            if cleaned is not None:
                si, ta, english = cleaned.sinhala, cleaned.tamil, cleaned.english
                if not (si and ta and english):
                    fb_si, fb_ta, fb_en = await self._fallback_translate(original, result.language)
                    si, ta, english = si or fb_si or "", ta or fb_ta or "", english or fb_en or ""
            else:
                si, ta, english = await self._fallback_translate(original, result.language)
                si, ta, english = si or "", ta or "", english or ""
            if seq != self._translate_seq and not result.is_final:
                return  # stale progressive
            self._latency.add("translate_ms", (time.monotonic() - t_tr) * 1000)
            # The model and the translator can both surface a blocked word.
            screened = {}
            dropped = False
            for label, text in (("sinhala", si), ("tamil", ta), ("english", english)):
                checked_line = content_filter.check(text or "")
                if checked_line.blocked:
                    self._log_blocked(label, checked_line, result.is_final)
                if checked_line.dropped:
                    dropped = True
                screened[label] = checked_line.text or ""
            if dropped:
                if result.is_final:
                    self._last_original = ""
                return
            si, ta, english = screened["sinhala"], screened["tamil"], screened["english"]
            if si:
                self._last_si = si
            if ta:
                self._last_ta = ta
            if english:
                self._last_en = english
            if result.is_final and si:
                self._context.append(si)
            if result.is_final:
                log.info(
                    "Final [%s] cleaned=%s si=%s ta=%s en=%s (%.0f ms)",
                    result.language,
                    cleaned is not None,
                    bool(si),
                    bool(ta),
                    bool(english),
                    (time.monotonic() - t_tr) * 1000,
                )
                if not (si and ta):
                    await self._send_error("Translation failed for the last sentence — check the backend log.")
        elif finals_only and not result.is_final:
            # ECO interim, only when the context cleaner is off.
            await self._send({
                "type": "translation",
                "sinhala": self._last_si,
                "tamil": self._last_ta,
                "english": self._last_en,
                "original": original,
                "isFinal": False,
                "lang": result.language,
                "latency": self._latency.snapshot(),
                "debug": result.debug if getattr(result, "debug", None) else self._stt.debug,
            })
            return

        if self._t_utterance_start:
            self._latency.add("e2e_ms", (time.monotonic() - self._t_utterance_start) * 1000)

        await self._send({
            "type": "translation",
            "sinhala": self._last_si,
            "tamil": self._last_ta,
            "english": english,
            "original": original if not hold_for_llm else "",
            "isFinal": result.is_final,
            "lang": result.language,
            "latency": self._latency.snapshot(),
            "debug": result.debug if getattr(result, "debug", None) else self._stt.debug,
        })
        if result.is_final:
            self._last_original = ""
            await self._send_usage()

    def _log_blocked(self, line: str, checked: FilterResult, is_final: bool) -> None:
        # Never log the words themselves.
        self._blocked += 1
        log.warning(
            "Content filter: %d word(s) %s in %s %s line",
            checked.blocked,
            "dropped" if checked.dropped else "masked",
            "final" if is_final else "interim",
            line,
        )

    async def _fallback_translate(self, text: str, language: str) -> tuple[str | None, str | None, str | None]:
        """Existing translator, used when the context cleaner is off or fails."""
        pair, english = await asyncio.gather(
            translate_to_sinhala_and_tamil(text, language),
            translate_mixed(text, "en", language),
            return_exceptions=True,
        )
        if isinstance(pair, BaseException):
            log.error("Fallback translation failed: %s", pair)
            si, ta = None, None
        else:
            si, ta = pair
        if isinstance(english, BaseException):
            log.error("Fallback English translation failed: %s", english)
            english = None
        return si, ta, english

    def clear_captions(self) -> None:
        """Operator Clear: forget the last lines so interims can't re-show them."""
        self._last_si = ""
        self._last_ta = ""
        self._last_en = ""
        self._last_original = ""
        self._context.clear()

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
            elif upper == "CLEAR":
                if session:
                    session.clear_captions()
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
