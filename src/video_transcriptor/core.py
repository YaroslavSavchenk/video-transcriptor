"""Link (or file) in, transcript out.

Flow for a URL:
1. Read the video's metadata and reject anything longer than MAX_DURATION_SECONDS.
2. If the platform has captions in the spoken language, use those (nothing is downloaded).
3. Otherwise fetch only the audio into a temporary folder, transcribe it locally and
   delete the folder again, also when something fails.
"""

from __future__ import annotations

import logging
import re
import shutil
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from . import asr, captions, links, sandbox
from .errors import TranscriptionError, classify_download_error
from .models import Segment, Transcript

log = logging.getLogger(__name__)

MAX_DURATION_SECONDS = 10 * 60
MAX_FILESIZE_BYTES = 500 * 1024 * 1024


def _is_url(source: str) -> bool:
    return urlparse(source).scheme in ("http", "https")


def _check_duration(duration: float | None) -> None:
    if duration and duration > MAX_DURATION_SECONDS:
        raise TranscriptionError(
            f"This video is {duration / 60:.1f} minutes long. The limit is "
            f"{MAX_DURATION_SECONDS // 60} minutes.",
            kind="video", title="Video too long",
            hint="Pick a shorter video (Reels, Shorts and TikToks are usually well under the limit).",
        )


def _ydl_options(cookies_from_browser: str | None, cookies_file: str | None, **extra) -> dict:
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True, "noprogress": True,
        # Only the YouTube/Instagram/TikTok extractors: no generic "any website" downloader.
        "allowed_extractors": links.ALLOWED_EXTRACTORS,
    }
    # YouTube needs a JavaScript runtime. The `deno` dependency installs one next to Python,
    # which isn't on PATH unless the virtualenv is activated.
    if not shutil.which("deno"):
        for name in ("deno", "deno.exe"):
            candidate = Path(sys.executable).parent / name
            if candidate.is_file():
                opts["js_runtimes"] = {"deno": {"path": str(candidate)}}
                break
    if cookies_from_browser:
        browser, _, profile = cookies_from_browser.partition(":")
        if browser.lower() == "firefox" and not profile:
            profile = _windows_firefox_profile() or ""
        opts["cookiesfrombrowser"] = (browser, profile or None)
    if cookies_file:
        opts["cookiefile"] = cookies_file
    opts.update(extra)
    return opts


def _windows_firefox_profile(users_dir: Path = Path("/mnt/c/Users")) -> str | None:
    """Under WSL, find the Windows Firefox profile so `--cookies-from-browser firefox` just works.

    Only used when there is no Linux Firefox profile. Picks the profile whose cookies were
    updated most recently. (Chrome/Edge cookies on Windows are encrypted and can't be read
    from WSL.)
    """
    if (Path.home() / ".mozilla" / "firefox").is_dir() or not users_dir.is_dir():
        return None
    try:
        cookie_dbs = list(users_dir.glob("*/AppData/Roaming/Mozilla/Firefox/Profiles/*/cookies.sqlite"))
    except OSError:
        return None
    if not cookie_dbs:
        return None
    newest = max(cookie_dbs, key=lambda p: p.stat().st_mtime)
    log.info("Using Windows Firefox profile %s", newest.parent)
    return str(newest.parent)


def _first_entry(info: dict) -> dict:
    """A single video. Instagram posts with several clips count as one (first clip)."""
    if info.get("_type") == "playlist":
        if info.get("extractor_key") != "Instagram":
            raise TranscriptionError("This link points to a playlist or channel, not to a single video.",
                                     kind="link", title="That's not a video",
                                     hint="Open the video itself, then use Share → Copy link.")
        entries = [e for e in info.get("entries") or [] if e and e.get("_type", "video") == "video"]
        if not entries:
            raise TranscriptionError("There's no video at this link.", kind="link",
                                     title="No video found", hint="Open the video itself and copy its link.")
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
            # TikTok's separate "audio" format is the post's sound track, which can be a
            # licensed song instead of what's said in the video, so take the video's own audio.
            format="bestaudio[format_id!=audio]/best[acodec!=none]/best",
            outtmpl=str(tmpdir / "audio.%(ext)s"),
            max_filesize=MAX_FILESIZE_BYTES,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            try:
                info = _first_entry(ydl.extract_info(url, download=False))
            except yt_dlp.utils.DownloadError as exc:
                raise classify_download_error(exc, url, bool(cookies_from_browser or cookies_file)) from exc

            if info.get("live_status") in ("is_live", "is_upcoming"):
                raise TranscriptionError(
                    "Live streams and premieres can't be transcribed while they're live.",
                    kind="video", title="Live stream",
                    hint="Wait until the recording is published, then try again.")
            duration = info.get("duration")
            _check_duration(duration)
            title = info.get("title")

            if use_captions:
                transcript = _try_captions(ydl, info, language)
                if transcript:
                    transcript.title, transcript.url, transcript.duration = title, url, duration
                    transcript.extra.update(_video_meta(info))
                    return transcript

            try:
                ydl.process_ie_result(info, download=True)
            except yt_dlp.utils.DownloadError as exc:
                raise classify_download_error(exc, url, bool(cookies_from_browser or cookies_file)) from exc

        files = [p for p in tmpdir.iterdir()
                 if p.is_file() and p.name.startswith("audio.") and not p.name.endswith(".part")]
        if not files:
            raise TranscriptionError("The video was found, but its audio couldn't be downloaded.",
                                     kind="platform", title="Couldn't download the audio",
                                     hint="Try again in a minute. If it keeps failing, update the app.")
        # Decode in an isolated, resource-limited process: the file comes from the internet.
        audio = sandbox.decode_audio(files[0], MAX_DURATION_SECONDS)
        _check_duration(len(audio) / sandbox.SAMPLE_RATE)
        segments, detected, audio_duration = _run_asr(audio, model, language, device)
        if keep_media_dir:
            Path(keep_media_dir).mkdir(parents=True, exist_ok=True)
            shutil.copy2(files[0], keep_media_dir)
        return Transcript(
            segments, detected, "speech-recognition", title, url, duration or audio_duration,
            extra={"model": model, **_video_meta(info)},
        )
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def _video_meta(info: dict) -> dict:
    """Details used to give saved transcripts a recognisable name."""
    return {
        "channel": info.get("channel") or info.get("uploader_id") or info.get("uploader"),
        "uploader": info.get("uploader"),
        "description": (info.get("description") or "")[:300],
        "platform": info.get("extractor_key"),
    }


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


def _run_asr(audio, model: str, language: str | None, device: str):
    try:
        return asr.transcribe_file(audio, model, language, device)
    except Exception as exc:
        log.exception("Speech recognition failed")
        raise TranscriptionError(
            "The speech recognition step crashed while processing the audio.",
            kind="app", title="Speech recognition failed",
            hint="Try again. If it keeps happening, try another model or restart the app.",
            technical=f"{type(exc).__name__}: {exc}",
        ) from exc


def _transcribe_local(path: Path, *, language: str | None, model: str, device: str) -> Transcript:
    tmpdir = Path(tempfile.mkdtemp(prefix="video-transcriptor-"))
    try:
        audio = sandbox.decode_audio(path, MAX_DURATION_SECONDS, workdir=tmpdir)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    _check_duration(len(audio) / sandbox.SAMPLE_RATE)
    segments, detected, duration = _run_asr(audio, model, language, device)
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
        raise TranscriptionError(f"There's no model called {model!r}.", kind="settings",
                                 title="Unknown model", hint=f"Choose one of: {', '.join(asr.MODELS)}.")
    if model in asr.ENGLISH_ONLY_MODELS:
        if language not in (None, "en"):
            raise TranscriptionError(
                f"The model {model} only understands English.", kind="settings",
                title="Model and language don't match",
                hint="Pick a multilingual model such as large-v3-turbo for other languages.",
            )
        language = "en"

    if _is_url(source) or re.match(r"^(www\.|m\.)?(youtube\.com|youtu\.be|instagram\.com|(vm\.|vt\.)?tiktok\.com)/", source, re.I):
        return _transcribe_url(
            links.clean_link(source),
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
    raise TranscriptionError("That's not a web link (http/https) or an existing file.", kind="link",
                             title="Not a link", hint="Paste the full link, starting with https://")
