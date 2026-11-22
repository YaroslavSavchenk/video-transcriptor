"""Local web page: paste a link, get a transcript."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path

from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from . import asr, core, formats, links, storage
from .errors import TranscriptionError
from .jobs import JobManager

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


def _user_error(kind: str, title: str, message: str, hint: str | None = None) -> HTTPException:
    return HTTPException(400, TranscriptionError(message, kind=kind, title=title, hint=hint).to_dict())


class TranscribeRequest(BaseModel):
    url: str = Field(max_length=2048)
    language: str | None = Field(default=None, max_length=10)
    model: str | None = None
    use_captions: bool = True
    force: bool = False  # transcribe again even if this video is already in the library


class OpenRequest(BaseModel):
    id: str | None = Field(default=None, max_length=300)


class IdRequest(BaseModel):
    id: str = Field(max_length=300)


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
    jobs = JobManager()
    core.cleanup_stale_temp_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        # Closing the app (SIGTERM) cancels running work so temp files get cleaned up.
        await asyncio.to_thread(jobs.shutdown)

    app = FastAPI(title="video-transcriptor", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        return JSONResponse({"detail": TranscriptionError(
            "The request wasn't valid. If you pasted something very long, check that it's a single "
            "video link.", kind="link", title="Invalid input").to_dict()}, status_code=400)
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
    library = storage.Library(save_dir)
    index_html = files("video_transcriptor").joinpath("static/index.html").read_text("utf-8")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return index_html

    @app.get("/api/options")
    def options() -> dict:
        return {"models": list(asr.MODELS), "default_model": asr.DEFAULT_MODEL,
                "english_only_models": list(asr.ENGLISH_ONLY_MODELS),
                "max_minutes": core.MAX_DURATION_SECONDS // 60, "save_dir": storage.display_path(save_dir),
                "running_job": (job.id if (job := jobs.running()) else None)}

    def prepare(req: TranscribeRequest) -> tuple[str, str | None, dict | None]:
        """Validate a request. Returns (clean url, language, existing transcript or None)."""
        try:
            url = links.clean_link(req.url)
        except TranscriptionError as exc:
            raise HTTPException(400, exc.to_dict()) from exc
        language = (req.language or "").strip().lower() or None
        if language and not re.fullmatch(r"[a-z]{2,3}", language):
            raise _user_error("settings", "Unknown language", "Choose a language from the list.")
        if req.model is not None and req.model not in asr.MODELS:
            raise _user_error("settings", "Unknown model", "Choose a model from the list.")
        existing = None if req.force else library.find_by_url(url)
        return url, language, existing

    def run(req: TranscribeRequest, url: str, language: str | None, control: core.Control) -> dict:
        started = time.monotonic()
        t = core.transcribe(
            url, language=language, model=req.model, use_captions=req.use_captions,
            cookies_from_browser=cookies_from_browser, cookies_file=cookies_file, control=control,
        )
        control.stage("Saving…")
        result = t.to_dict()
        result["elapsed_seconds"] = round(time.monotonic() - started, 1)
        result["files"] = {fmt: formats.render(t, fmt) for fmt in ("txt", "srt", "vtt")}
        try:
            result["saved_id"] = library.save(t)
        except OSError as exc:
            log.exception("Could not save transcript")
            result["save_error"] = str(exc)
        return result

    @app.post("/api/jobs")
    def start_job(req: TranscribeRequest) -> dict:
        url, language, existing = prepare(req)
        if existing:
            return {"existing": existing}
        try:
            job = jobs.start(lambda control: run(req, url, language, control))
        except TranscriptionError as exc:
            raise HTTPException(409, exc.to_dict()) from exc
        return job.view()

    @app.get("/api/jobs/{job_id}")
    def job_status(job_id: str) -> dict:
        job = jobs.get(job_id)
        if not job:
            raise HTTPException(404, TranscriptionError(
                "This transcription isn't known (anymore). The app may have restarted.",
                kind="app", title="Transcription not found", hint="Start it again.").to_dict())
        return job.view()

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict:
        job = jobs.cancel(job_id)
        return job.view() if job else {"status": "unknown"}

    # Synchronous variant for scripts: same as a job, but waits for the result.
    @app.post("/api/transcribe")
    def transcribe(req: TranscribeRequest) -> dict:
        url, language, existing = prepare(req)
        if existing:
            return {"existing": existing}
        try:
            return run(req, url, language, core.Control())
        except TranscriptionError as exc:
            raise HTTPException(422, exc.to_dict()) from exc
        except Exception as exc:
            log.exception("Transcription failed")
            raise HTTPException(500, TranscriptionError(
                "An unexpected error happened inside the app.", kind="app",
                title="Something went wrong in the app",
                hint="Try again. If it keeps happening, restart the app or update it.",
                technical=f"{type(exc).__name__}: {exc}").to_dict()) from exc

    @app.get("/api/transcripts")
    def transcripts(q: str = Query("", max_length=200), offset: int = Query(0, ge=0),
                    limit: int = Query(50, ge=1, le=200)) -> dict:
        return library.query(q, offset, limit)

    @app.get("/api/transcript")
    def transcript(id: str = Query(max_length=300)) -> dict:
        try:
            return library.get(id)
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(404, "Transcript not found.") from exc

    @app.delete("/api/transcript")
    def delete_transcript(id: str = Query(max_length=300)) -> dict:
        try:
            library.delete(id)
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(404, "Transcript not found.") from exc
        return {"ok": True}

    @app.post("/api/transcript/restore")
    def restore_transcript(req: IdRequest) -> dict:
        try:
            return {"id": library.restore(req.id)}
        except (FileNotFoundError, OSError) as exc:
            raise HTTPException(404, "Nothing to restore.") from exc

    @app.post("/api/open-folder")
    def open_folder(req: OpenRequest) -> dict:
        target = save_dir
        if req.id:
            try:
                path = library._path(req.id)
                target = path if path.is_file() else save_dir
            except FileNotFoundError:
                pass
        save_dir.mkdir(parents=True, exist_ok=True)
        storage.open_in_file_manager(target)
        return {"ok": True}

    return app
