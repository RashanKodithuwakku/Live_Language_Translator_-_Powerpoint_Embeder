"""
websocket_handler.py
────────────────────
Lifecycle of one translation WebSocket.

  1. Frontend connects to /ws/translate?lang=<si-LK|ta-LK|en-US> (the
     speaker's main language; the others stay enabled as alternatives)
     (operator clicked Start, or the frontend is
     auto-reconnecting after a drop) → a TranslationSession starts
     immediately. A reconnect therefore rebuilds the Google stream with no
     operator action.
  2. Binary frames (LINEAR16, 16 kHz, mono, ~100 ms each) are cleaned up by
     AudioProcessor in a worker thread and fed to the STT session.
  3. Each final transcript is translated to Sinhala + Tamil concurrently
     and pushed back as one message.
  4. "STOP" text frame, or disconnect → session torn down.

Frontend → backend
  • binary: PCM audio chunk
  • text "START": (re)start a session on the same socket
  • text "STOP":  end the session, keep the socket open

Backend → frontend (JSON)
  {"type": "translation", "sinhala", "tamil", "original", "isFinal": true, "lang"}
  {"type": "status", "message"}
  {"type": "error",  "message"}
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import WebSocket, WebSocketDisconnect

from audio_processor import AudioProcessor
from stt_client import STTSession
from translation_client import translate_to_sinhala_and_tamil

log = logging.getLogger("ws")

ERROR_REPEAT_SUPPRESS_S = 15.0


class TranslationSession:
    def __init__(self, websocket: WebSocket, send_lock: asyncio.Lock, language: str | None):
        self._ws = websocket
        self._send_lock = send_lock
        self._processor = AudioProcessor()
        self._stt = STTSession(language)
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self._last_error: tuple[str, float] = ("", 0.0)

    async def start(self) -> None:
        self._running = True
        self._tasks = [
            asyncio.create_task(self._deliver_translations(), name="deliver-translations"),
            asyncio.create_task(self._forward_stt_errors(), name="forward-stt-errors"),
        ]
        await self._send({
            "type": "status",
            "message": f"Translation session started ({self._stt.primary_language} first)",
        })

    async def stop(self, notify: bool = True) -> None:
        if not self._running:
            return
        self._running = False
        self._stt.close()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        if notify:
            await self._send({"type": "status", "message": "Translation session stopped"})

    async def push_audio(self, pcm: bytes) -> None:
        if not self._running:
            return
        cleaned = await asyncio.to_thread(self._processor.process, pcm)
        self._stt.feed(cleaned)

    async def _deliver_translations(self) -> None:
        while True:
            final = await self._stt.results.get()
            sinhala, tamil = await translate_to_sinhala_and_tamil(final.text, final.language_code)
            if sinhala is None or tamil is None:
                await self._send_error("Translation service error — showing partial captions")
            await self._send({
                "type": "translation",
                "sinhala": sinhala or "",
                "tamil": tamil or "",
                "original": final.text,
                "isFinal": True,
                "lang": final.language_code,
            })

    async def _forward_stt_errors(self) -> None:
        while True:
            message = await self._stt.errors.get()
            await self._send_error(f"Speech recognition interrupted, reconnecting: {message}")

    async def _send_error(self, message: str) -> None:
        last_message, last_at = self._last_error
        now = time.monotonic()
        if message == last_message and now - last_at < ERROR_REPEAT_SUPPRESS_S:
            return
        self._last_error = (message, now)
        await self._send({"type": "error", "message": message})

    async def _send(self, payload: dict) -> None:
        try:
            async with self._send_lock:
                await self._ws.send_text(json.dumps(payload, ensure_ascii=False))
        except Exception:
            # Socket already gone; the receive loop will clean up.
            pass


async def handle_translation_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    language = websocket.query_params.get("lang")
    log.info("Client connected: %s (speaker language: %s)", websocket.client, language or "default")
    send_lock = asyncio.Lock()
    session: TranslationSession | None = TranslationSession(websocket, send_lock, language)
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

            command = (message.get("text") or "").strip().upper()
            if command == "STOP" and session:
                await session.stop()
                session = None
            elif command == "START":
                if session:
                    await session.stop(notify=False)
                session = TranslationSession(websocket, send_lock, language)
                await session.start()
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("WebSocket handler error")
    finally:
        if session:
            await session.stop(notify=False)
        log.info("Client disconnected: %s", websocket.client)
