"""Local web page: paste a link, get a transcript."""

from __future__ import annotations

import logging
import re
import time
from importlib.resources import files

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from . import asr, core, formats

log = logging.getLogger(__name__)


class TranscribeRequest(BaseModel):
    url: str = Field(max_length=2048)
    language: str | None = Field(default=None, max_length=10)
    model: str | None = None
    use_captions: bool = True


def create_app(cookies_from_browser: str | None = None, cookies_file: str | None = None) -> FastAPI:
    app = FastAPI(title="video-transcriptor", docs_url=None, redoc_url=None)
    index_html = files("video_transcriptor").joinpath("static/index.html").read_text("utf-8")

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return index_html

    @app.get("/api/options")
    def options() -> dict:
        return {"models": list(asr.MODELS), "default_model": asr.DEFAULT_MODEL,
                "english_only_models": list(asr.ENGLISH_ONLY_MODELS),
                "max_minutes": core.MAX_DURATION_SECONDS // 60}

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
        return result

    return app
