"""
main.py
───────
FastAPI application entry point for the Live Translator backend.

Why FastAPI over Flask + Flask-SocketIO?
  FastAPI is chosen because:
  1. Native async WebSocket support (no socketio eventlet/gevent monkey-patching).
  2. asyncio.gather() for concurrent translations works naturally in the
     same event loop with no thread-safety caveats.
  3. Pydantic validation for any REST endpoints we may add (health check, etc.).
  4. Starlette's WebSocket API maps 1-to-1 with our audio streaming model —
     we receive raw binary frames, not JSON events, which is awkward in
     Flask-SocketIO's message-type model.

Run locally:
  uvicorn main:app --host 127.0.0.1 --port 8000 --reload

Environment:
  Set GOOGLE_APPLICATION_CREDENTIALS in .env (see .env.example).
"""

import os
from pathlib import Path

# ── Load .env before any Google client initialisation ───────────────────────
from dotenv import load_dotenv

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)
else:
    print(
        "[WARN] .env file not found — ensure GOOGLE_APPLICATION_CREDENTIALS "
        "and GOOGLE_CLOUD_PROJECT are set in your environment."
    )

# Verify credentials are set before importing Google clients
_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not _creds:
    raise RuntimeError(
        "GOOGLE_APPLICATION_CREDENTIALS is not set. "
        "Copy .env.example to .env and fill in the path to your service account key."
    )

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from websocket_handler import handle_translation_websocket

# ── FastAPI app ──────────────────────────────────────────────────────────────
app = FastAPI(
    title="Live Translator Backend",
    description="Real-time multilingual speech translation for live events",
    version="1.0.0",
)

# Allow the Vite dev server (port 5173) and any localhost origin.
# This runs entirely on localhost — no public exposure.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── REST endpoints ────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    """Simple health probe used by the frontend to verify the backend is up."""
    return {
        "status": "ok",
        "credentials_configured": bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS")),
        "project": os.getenv("GOOGLE_CLOUD_PROJECT", "not-set"),
    }


# ── WebSocket endpoint ────────────────────────────────────────────────────────
@app.websocket("/ws/translate")
async def translation_ws(websocket: WebSocket):
    """
    Primary WebSocket endpoint.
    The frontend connects here when the operator clicks "Start Translation".
    See websocket_handler.py for the full session lifecycle documentation.
    """
    await handle_translation_websocket(websocket)


# ── Dev entrypoint ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn

    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))

    print(f"[INFO] Starting Live Translator backend on ws://{host}:{port}")
    uvicorn.run("main:app", host=host, port=port, reload=True)
