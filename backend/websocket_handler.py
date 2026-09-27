"""
websocket_handler.py
────────────────────
FastAPI WebSocket endpoint logic, separated from main.py for clarity.

Session lifecycle
─────────────────
  1. Frontend connects → TranslationSession is created.
  2. Frontend sends binary frames (raw PCM audio).
  3. Frames are noise-reduced then queued for STT.
  4. STT yields final transcripts → both translations run concurrently.
  5. A JSON message is pushed back to the frontend WebSocket.
  6. On disconnect or Stop command, the session is torn down gracefully.
  7. If the frontend reconnects (same or new socket), a fresh session
     starts immediately without operator intervention.

Message protocol (frontend → backend)
──────────────────────────────────────
  • Binary frames: raw PCM int16 audio chunks (16 kHz, mono, LINEAR16)
  • Text frame "STOP": signals the operator clicked Stop; ends the session
    cleanly (does NOT close the WebSocket itself, so the frontend can
    reconnect without a page reload)

Message protocol (backend → frontend)
──────────────────────────────────────
  JSON object:
  {
    "type":     "translation",
    "sinhala":  "<Sinhala text>",
    "tamil":    "<Tamil text>",
    "original": "<original transcript>",
    "isFinal":  true,
    "lang":     "<detected language code e.g. si-LK>"
  }

  OR error notification:
  {
    "type":    "error",
    "message": "<human-readable error>"
  }

  OR status:
  {
    "type":    "status",
    "message": "<info string>"
  }
"""

import asyncio
import json
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from audio_processor import process_audio_chunk
from stt_client import STTSession
from translation_client import translate_to_sinhala_and_tamil


class TranslationSession:
    """
    Manages one operator-initiated translation session.

    A single operator may stop and restart multiple times during an event.
    Each Start click creates a new TranslationSession; each Stop (or
    disconnect) destroys it cleanly.
    """

    def __init__(self, websocket: WebSocket):
        self._ws = websocket
        self._audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start background STT + translation pipeline."""
        self._running = True
        stt_session = STTSession(self._audio_queue)

        # The STT pipeline runs as a background task so audio ingestion
        # and result pushing are decoupled.
        pipeline_task = asyncio.create_task(
            self._run_pipeline(stt_session),
            name="stt-pipeline",
        )
        self._tasks.append(pipeline_task)
        await self._send_status("Translation session started")

    async def stop(self) -> None:
        """Gracefully shut down the STT session and cancel tasks."""
        if not self._running:
            return
        self._running = False

        # Signal the STT generator to stop
        await self._audio_queue.put(None)

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

        self._tasks.clear()
        await self._send_status("Translation session stopped")

    async def push_audio(self, pcm_bytes: bytes) -> None:
        """
        Accept a raw PCM chunk from the WebSocket, apply noise reduction,
        and queue it for the STT stream.
        Drop the chunk (with a warning) if the queue is full — this prevents
        memory bloat if the STT stream temporarily stalls.
        """
        if not self._running:
            return

        processed = process_audio_chunk(pcm_bytes)

        try:
            self._audio_queue.put_nowait(processed)
        except asyncio.QueueFull:
            print("[WARN] Audio queue full — dropping chunk to avoid lag")

    async def _run_pipeline(self, stt_session: STTSession) -> None:
        """
        Core pipeline: consume STT results and push translations to the frontend.
        Runs until cancelled.
        """
        try:
            async for transcript, lang_code in stt_session.stream_results():
                if not self._running:
                    break

                try:
                    sinhala, tamil = await translate_to_sinhala_and_tamil(
                        transcript, lang_code
                    )

                    message = {
                        "type": "translation",
                        "sinhala": sinhala,
                        "tamil": tamil,
                        "original": transcript,
                        "isFinal": True,
                        "lang": lang_code,
                    }
                    await self._ws.send_text(json.dumps(message))

                except Exception as translate_err:
                    print(f"[ERROR] Translation failed: {translate_err}")
                    await self._send_error(f"Translation error: {translate_err}")

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            print(f"[ERROR] STT pipeline crashed: {exc}")
            await self._send_error(f"STT pipeline error: {exc}")

    async def _send_status(self, message: str) -> None:
        try:
            await self._ws.send_text(
                json.dumps({"type": "status", "message": message})
            )
        except Exception:
            pass

    async def _send_error(self, message: str) -> None:
        try:
            await self._ws.send_text(
                json.dumps({"type": "error", "message": message})
            )
        except Exception:
            pass


# ── WebSocket endpoint handler ───────────────────────────────────────────────
async def handle_translation_websocket(websocket: WebSocket) -> None:
    """
    Main WebSocket handler registered in main.py.

    Handles the full connection lifecycle including:
      - Accepting the connection
      - Routing binary frames to audio processing
      - Routing text control commands ("STOP")
      - Graceful session teardown on disconnect
    """
    await websocket.accept()
    print(f"[WS] Client connected: {websocket.client}")

    session: Optional[TranslationSession] = None

    try:
        # Auto-start the session immediately on connection.
        # The operator clicking "Start" in the UI triggers the WebSocket
        # connection itself; no separate handshake message is needed.
        session = TranslationSession(websocket)
        await session.start()

        while True:
            # receive_bytes or receive_text, whichever arrives first
            data = await websocket.receive()

            if "bytes" in data and data["bytes"]:
                # Binary frame → audio chunk
                if session:
                    await session.push_audio(data["bytes"])

            elif "text" in data and data["text"]:
                text = data["text"].strip().upper()

                if text == "STOP":
                    if session:
                        await session.stop()
                        session = None

                elif text == "START":
                    # Operator restarted mid-session (e.g. after a Stop)
                    if session:
                        await session.stop()
                    session = TranslationSession(websocket)
                    await session.start()

    except WebSocketDisconnect:
        print(f"[WS] Client disconnected")

    except Exception as exc:
        print(f"[WS] Unexpected error: {exc}")

    finally:
        if session:
            await session.stop()
        print("[WS] Session cleaned up")
