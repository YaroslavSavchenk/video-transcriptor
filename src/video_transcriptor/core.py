"""Link (or file) in, transcript out.

Flow for a URL:
1. Read the video's metadata and reject anything longer than MAX_DURATION_SECONDS.
2. If the platform has captions in the spoken language, use those (nothing is downloaded).
3. Otherwise fetch only the audio into a temporary folder, transcribe it locally and
   delete the folder again, also when something fails.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from . import asr, captions
from .models import Segment, Transcript

log = logging.getLogger(__name__)

MAX_DURATION_SECONDS = 10 * 60
MAX_FILESIZE_BYTES = 500 * 1024 * 1024


class TranscriptionError(Exception):
    """An error with a message that is safe and useful to show to the user."""


def _is_url(source: str) -> bool:
    return urlparse(source).scheme in ("http", "https")


def _check_duration(duration: float | None) -> None:
    if duration and duration > MAX_DURATION_SECONDS:
        raise TranscriptionError(
            f"This video is {duration / 60:.1f} minutes long; the limit is "
            f"{MAX_DURATION_SECONDS // 60} minutes."
        )


def _ydl_options(cookies_from_browser: str | None, cookies_file: str | None, **extra) -> dict:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True}
    # YouTube needs a JavaScript runtime. The `deno` dependency installs one next to Python,
    # which isn't on PATH unless the virtualenv is activated.
    if not shutil.which("deno"):
        for name in ("deno", "deno.exe"):
            candidate = Path(sys.executable).parent / name
            if candidate.is_file():
                opts["js_runtimes"] = {"deno": {"path": str(candidate)}}
                break
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies_file:
        opts["cookiefile"] = cookies_file
    opts.update(extra)
    return opts


def _friendly_download_error(exc: Exception) -> TranscriptionError:
    msg = str(exc).removeprefix("ERROR: ")
    lower = msg.lower()
    if any(w in lower for w in ("login", "log in", "cookies", "private", "rate-limit")):
        msg += (
            "\n\nThis platform wants a logged-in session for this video. Start the tool with "
            "--cookies-from-browser firefox (or --cookies cookies.txt) and try again."
        )
    elif "unsupported url" in lower:
        msg = "This link isn't supported. Use a link to an Instagram Reel, YouTube video/Short or TikTok."
    return TranscriptionError(msg)


def _first_entry(info: dict) -> dict:
    if info.get("_type") == "playlist":
        entries = [e for e in info.get("entries") or [] if e]
        if not entries:
            raise TranscriptionError("No video found at this link.")
        return entries[0]
    return info


def _transcribe_url(
    url: str,
    *,
    language: str | None,
    model: str,
    use_captions: bool,
    device: str,
    cookies_from_browser: str | None,
    cookies_file: str | None,
    keep_media_dir: str | None,
) -> Transcript:
    import yt_dlp

    tmpdir = Path(tempfile.mkdtemp(prefix="video-transcriptor-"))
    try:
        opts = _ydl_options(
            cookies_from_browser,
            cookies_file,
            format="bestaudio/best",
            outtmpl=str(tmpdir / "audio.%(ext)s"),
            max_filesize=MAX_FILESIZE_BYTES,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = _first_entry(ydl.extract_info(url, download=False))
            except yt_dlp.utils.DownloadError as exc:
                raise _friendly_download_error(exc) from exc

            duration = info.get("duration")
            _check_duration(duration)
            title = info.get("title")

            if use_captions:
                transcript = _try_captions(ydl, info, language)
                if transcript:
                    transcript.title, transcript.url, transcript.duration = title, url, duration
                    return transcript

            try:
                ydl.process_ie_result(info, download=True)
            except yt_dlp.utils.DownloadError as exc:
                raise _friendly_download_error(exc) from exc

        files = [p for p in tmpdir.iterdir() if p.is_file() and not p.name.endswith(".part")]
        if not files:
            raise TranscriptionError("Couldn't fetch the audio of this video.")
        if not _has_audio(files[0]):
            raise TranscriptionError(
                "The fetched video has no sound track. Either the video is silent, or the platform "
                "only serves the audio to logged-in users (common on Instagram): start the tool with "
                "--cookies-from-browser firefox and try again."
            )
        segments, detected, audio_duration = asr.transcribe_file(files[0], model, language, device)
        _check_duration(audio_duration)
        if keep_media_dir:
            Path(keep_media_dir).mkdir(parents=True, exist_ok=True)
            shutil.copy2(files[0], keep_media_dir)
        return Transcript(
            segments, detected, "speech-recognition", title, url, duration or audio_duration,
            extra={"model": model},
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _has_audio(path: Path) -> bool:
    import av

    try:
        with av.open(str(path)) as container:
            return any(s.type == "audio" for s in container.streams)
    except Exception:
        return True  # let the transcriber report the real problem


def _try_captions(ydl, info: dict, language: str | None) -> Transcript | None:
    track = captions.choose_track(info, language)
    if not track:
        return None
    lang, fmt, is_auto = track
    try:
        data = ydl.urlopen(fmt["url"]).read().decode("utf-8", errors="replace")
        segments: list[Segment] = captions.parse(data, fmt["ext"])
    except Exception as exc:  # captions are a shortcut; fall back to speech recognition
        log.warning("Could not use captions (%s); falling back to speech recognition", exc)
        return None
    if not segments:
        return None
    return Transcript(segments, lang, "captions", extra={"automatic_captions": is_auto})


def _transcribe_local(path: Path, *, language: str | None, model: str, device: str) -> Transcript:
    try:
        import av

        with av.open(str(path)) as container:
            if container.duration:
                _check_duration(container.duration / av.time_base)
    except TranscriptionError:
        raise
    except Exception as exc:
        raise TranscriptionError(f"Can't read this file as audio or video: {exc}") from exc
    segments, detected, duration = asr.transcribe_file(path, model, language, device)
    return Transcript(segments, detected, "speech-recognition", path.name, None, duration, extra={"model": model})


def transcribe(
    source: str,
    *,
    language: str | None = None,
    model: str | None = None,
    use_captions: bool = True,
    device: str = "auto",
    cookies_from_browser: str | None = None,
    cookies_file: str | None = None,
    keep_media_dir: str | None = None,
) -> Transcript:
    """Transcribe a video link (Instagram, YouTube, TikTok, ...) or a local file."""
    source = source.strip()
    language = (language or "").strip().lower() or None
    if model is None:
        # English is the main use case; other languages get the best multilingual model.
        model = asr.DEFAULT_MODEL if language in (None, "en") else asr.DEFAULT_MULTILINGUAL_MODEL
    if model not in asr.MODELS:
        raise TranscriptionError(f"Unknown model {model!r}; choose from {', '.join(asr.MODELS)}.")
    if model in asr.ENGLISH_ONLY_MODELS:
        if language not in (None, "en"):
            raise TranscriptionError(
                f"The model {model} only understands English. Pick a multilingual model "
                "such as large-v3-turbo or small for other languages."
            )
        language = "en"

    if _is_url(source):
        return _transcribe_url(
            source,
            language=language,
            model=model,
            use_captions=use_captions,
            device=device,
            cookies_from_browser=cookies_from_browser,
            cookies_file=cookies_file,
            keep_media_dir=keep_media_dir,
        )
    path = Path(source).expanduser()
    if path.is_file():
        return _transcribe_local(path, language=language, model=model, device=device)
    raise TranscriptionError("That's not a link (http/https) or an existing file.")
