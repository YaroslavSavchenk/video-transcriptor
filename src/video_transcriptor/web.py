"""Local web page: paste a link, get a transcript."""

from __future__ import annotations

import logging
import re
import time
from importlib.resources import files
from pathlib import Path

from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import asr, core, formats, storage

log = logging.getLogger(__name__)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Everything the page needs is inline; nothing may be loaded from elsewhere or embed this page.
SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
        "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    ),
    "X-Frame-Options": "DENY",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def _hostname(value: str) -> str:
    """Host part of a Host header or Origin URL, without port or IPv6 brackets."""
    netloc = urlparse(value).netloc if "://" in value else value
    return (urlparse(f"//{netloc}").hostname or "").lower()


class TranscribeRequest(BaseModel):
    url: str = Field(max_length=2048)
    language: str | None = Field(default=None, max_length=10)
    model: str | None = None
    use_captions: bool = True


class OpenRequest(BaseModel):
    file: str | None = None


def create_app(
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
    save_dir: Path | None = None,
    allowed_hosts: set[str] | None = None,
) -> FastAPI:
    """`save_dir=None` saves into the `transcripts` folder inside the app folder.

    Only requests addressed to `allowed_hosts` (default: loopback names) are served. This
    blocks DNS-rebinding attacks, where a malicious website points its own domain at
    127.0.0.1 to read transcripts or start downloads that use the user's cookies.
    Pass {"*"} to allow any host (only sensible on a trusted network).
    """
    app = FastAPI(title="video-transcriptor", docs_url=None, redoc_url=None, openapi_url=None)
    allowed = {h.lower() for h in (allowed_hosts or LOOPBACK_HOSTS)}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if "*" not in allowed:
            if _hostname(request.headers.get("host", "")) not in allowed:
                return JSONResponse({"detail": "Host not allowed."}, status_code=403)
            # Browsers send Origin on cross-site requests; only our own page may call the API.
            origin = request.headers.get("origin")
            if origin and _hostname(origin) not in allowed:
                return JSONResponse({"detail": "Cross-site request blocked."}, status_code=403)
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response
    save_dir = save_dir or storage.default_dir()
    index_html = files("video_transcriptor").joinpath("static/index.html").read_text("utf-8")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return index_html

    @app.get("/api/options")
    def options() -> dict:
        return {"models": list(asr.MODELS), "default_model": asr.DEFAULT_MODEL,
                "english_only_models": list(asr.ENGLISH_ONLY_MODELS),
                "max_minutes": core.MAX_DURATION_SECONDS // 60, "save_dir": storage.display_path(save_dir)}

    # A plain `def` endpoint runs in FastAPI's thread pool, so the server stays responsive.
    @app.post("/api/transcribe")
    def transcribe(req: TranscribeRequest) -> dict:
        url = req.url.strip()
        if not core._is_url(url):
            raise HTTPException(400, "Paste a full link that starts with http:// or https://.")
        language = (req.language or "").strip().lower() or None
        if language and not re.fullmatch(r"[a-z]{2,3}", language):
            raise HTTPException(400, "Language must be a code like 'nl' or 'en'.")
        if req.model is not None and req.model not in asr.MODELS:
            raise HTTPException(400, f"Unknown model; choose from {', '.join(asr.MODELS)}.")

        started = time.monotonic()
        try:
            t = core.transcribe(
                url, language=language, model=req.model, use_captions=req.use_captions,
                cookies_from_browser=cookies_from_browser, cookies_file=cookies_file,
            )
        except core.TranscriptionError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            log.exception("Transcription failed")
            raise HTTPException(500, f"Something went wrong: {exc}") from exc

        result = t.to_dict()
        result["elapsed_seconds"] = round(time.monotonic() - started, 1)
        result["files"] = {fmt: formats.render(t, fmt) for fmt in ("txt", "srt", "vtt")}
        try:
            saved = storage.save(t, save_dir)
            result["saved_file"] = saved.name
        except OSError as exc:
            log.exception("Could not save transcript")
            result["save_error"] = str(exc)
        return result

    @app.get("/api/history")
    def history() -> list[dict]:
        return storage.list_saved(save_dir)

    @app.get("/api/history/{filename}")
    def history_item(filename: str) -> dict:
        try:
            return storage.read_saved(save_dir, filename)
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(404, "Transcript not found.") from exc

    @app.post("/api/open-folder")
    def open_folder(req: OpenRequest) -> dict:
        target = save_dir
        if req.file and Path(req.file).name == req.file and (save_dir / req.file).is_file():
            target = save_dir / req.file
        save_dir.mkdir(parents=True, exist_ok=True)
        storage.open_in_file_manager(target)
        return {"ok": True}

    return app
