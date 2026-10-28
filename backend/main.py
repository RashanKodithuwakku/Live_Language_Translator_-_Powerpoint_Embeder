"""
main.py
───────
FastAPI entry point for the Live Translator backend.

Why FastAPI rather than Flask + Flask-SocketIO?
  • Native asyncio WebSockets carrying raw binary audio frames — no
    Socket.IO event envelope and no eventlet/gevent monkey-patching.
  • asyncio.gather() for the two concurrent translations lives in the same
    event loop as the socket, with no thread-safety caveats.
  • Starlette's FileResponse supports HTTP Range requests, which the
    browser needs to seek inside slide videos.

Run for the event (from backend/, venv active):
  uvicorn main:app --host 127.0.0.1 --port 8000
"""

import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path)

for _stream in (sys.stdout, sys.stderr):
    # Windows consoles default to cp1252; captions are Sinhala/Tamil.
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


class _ProbeFilter(logging.Filter):
    """Drop access-log lines for Chrome DevTools discovery probes (/json/version, /json/list)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        path = str(args[2]) if len(args) > 2 else ""
        return not path.startswith("/json")


logging.getLogger("uvicorn.access").addFilter(_ProbeFilter())

_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not _creds:
    raise RuntimeError(
        "GOOGLE_APPLICATION_CREDENTIALS is not set. "
        "Copy .env.example to .env and fill in the path to your service account key."
    )
_creds_path = (Path(__file__).parent / _creds).resolve() if not Path(_creds).is_absolute() else Path(_creds)
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(_creds_path)
if not _creds_path.exists():
    log.warning("Service account key not found at %s - translation will fail until it is placed there.", _creds_path)

from fastapi import FastAPI, HTTPException, Request, WebSocket  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse  # noqa: E402

import presentation_service as presentations  # noqa: E402
from websocket_handler import handle_translation_websocket  # noqa: E402
import config  # noqa: E402
from llm_context import warm_client as warm_llm  # noqa: E402
from translation_client import warm_client  # noqa: E402
from usage_ledger import ledger  # noqa: E402

app = FastAPI(
    title="Live Translator Backend",
    description="Real-time multilingual speech translation for live events",
    version="1.2-advanced",
)

# Localhost-only event tool: allow the Vite dev/preview server origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index():
    """This is the API server; the operator UI is served by Vite on :5173."""
    key = "found" if _creds_path.exists() else "MISSING - see README"
    return f"""<!doctype html><meta charset="utf-8"><title>Live Translator backend</title>
<body style="font-family:system-ui;background:#121212;color:#cbd5e1;padding:2rem">
<h2>Live Translator backend is running</h2>
<p>Google key: <b>{key}</b></p>
<p>Open the app at <a style="color:#38bdf8" href="http://127.0.0.1:5173">http://127.0.0.1:5173</a>
(start it with <code>npm run dev</code> in the frontend folder).</p>
</body>"""


@app.on_event("startup")
async def _startup():
    log.info("Runtime: %s", config.summary())
    if not config.is_cache_mode():
        await warm_client()
        await warm_llm()


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "credentials_found": _creds_path.exists(),
        "project": os.getenv("GOOGLE_CLOUD_PROJECT", "not-set"),
        **config.summary(),
        "usage": ledger.snapshot(),
    }


@app.get("/api/usage")
async def usage():
    return ledger.snapshot()


@app.post("/api/budget/override")
async def budget_override():
    ledger.activate_override(4.0)
    return {"ok": True, "usage": ledger.snapshot()}


# ── Presentations ────────────────────────────────────────────────────────────
@app.post("/api/presentations")
async def upload_presentation(request: Request, filename: str = "presentation.pptx"):
    """Body: raw .pptx bytes (Content-Type: application/octet-stream)."""
    if not filename.lower().endswith(".pptx"):
        raise HTTPException(400, "Only .pptx files are converted on the server; PDFs load directly.")

    presentations.PRESENTATIONS_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(suffix=".pptx", dir=presentations.PRESENTATIONS_DIR)
    tmp_path = Path(tmp_name)
    received = 0
    try:
        with os.fdopen(fd, "wb") as fh:
            async for chunk in request.stream():
                received += len(chunk)
                if received > presentations.MAX_UPLOAD_BYTES:
                    raise HTTPException(413, "Presentation file is too large.")
                fh.write(chunk)
        if received == 0:
            raise HTTPException(400, "Empty upload.")

        log.info("Converting presentation %s (%.1f MB)", filename, received / 1e6)
        manifest = await asyncio.wait_for(
            asyncio.to_thread(presentations.process_pptx, tmp_path, filename),
            timeout=presentations.CONVERSION_TIMEOUT_S,
        )
        log.info("Presentation ready: %s via %s", manifest["id"], manifest["converter"])
        return manifest
    except presentations.PresentationError as exc:
        raise HTTPException(422, str(exc))
    except asyncio.TimeoutError:
        raise HTTPException(504, "Presentation conversion timed out.")
    finally:
        tmp_path.unlink(missing_ok=True)


def _existing_file(path_factory, *args) -> Path:
    try:
        path = path_factory(*args)
    except presentations.PresentationError as exc:
        raise HTTPException(400, str(exc))
    if not path.is_file():
        raise HTTPException(404, "Not found")
    return path


@app.get("/api/presentations/{presentation_id}")
async def presentation_manifest(presentation_id: str):
    """Lets the frontend restore the loaded deck after a browser refresh."""
    try:
        manifest = presentations.load_manifest(presentation_id)
    except presentations.PresentationError as exc:
        raise HTTPException(400, str(exc))
    if not manifest:
        raise HTTPException(404, "Presentation not found")
    return manifest


@app.get("/api/presentations/{presentation_id}/slides.pdf")
async def presentation_pdf(presentation_id: str):
    return FileResponse(_existing_file(presentations.pdf_path, presentation_id), media_type="application/pdf")


@app.get("/api/presentations/{presentation_id}/media/{name}")
async def presentation_media(presentation_id: str, name: str):
    path = _existing_file(presentations.media_path, presentation_id, name)
    return FileResponse(path, media_type=presentations.MIME_TYPES.get(path.suffix.lower()))


@app.delete("/api/presentations/{presentation_id}")
async def remove_presentation(presentation_id: str):
    try:
        presentations.delete_presentation(presentation_id)
    except presentations.PresentationError as exc:
        raise HTTPException(400, str(exc))
    return {"deleted": presentation_id}


# ── Live translation ─────────────────────────────────────────────────────────
@app.websocket("/ws/translate")
async def translation_ws(websocket: WebSocket):
    await handle_translation_websocket(websocket)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
    )
