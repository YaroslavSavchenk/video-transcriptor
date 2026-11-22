"""Check and clean up pasted links before anything is fetched.

The link box is the app's only input from the outside world, and links often come from
other people. So a link is only accepted when it is clearly a single video on YouTube,
Instagram or TikTok:

- only https (http is upgraded), no user:password@, no custom ports, no control characters
- only known hosts: nothing on your own network, no file://, no other websites
- only video paths (no channels, profiles, playlists, photo posts)
- the #fragment is removed: yt-dlp reads hidden "smuggled" options from it
- tracking and playlist parameters are dropped

On top of that, yt-dlp itself is limited to the YouTube, Instagram and TikTok extractors
(see ALLOWED_EXTRACTORS), so even a redirect can't make it fetch from anywhere else.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from .errors import TranscriptionError

MAX_LENGTH = 2048

# Regexes for yt-dlp's `allowed_extractors` (matched against extractor names).
ALLOWED_EXTRACTORS = [
    r"youtube", r"YoutubeYtBe", r"youtube:truncated_id", r"youtube:truncated_url",
    r"Instagram", r"TikTok", r"vm\.tiktok",
]

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{6,20}$")
_IG_ID = re.compile(r"^[A-Za-z0-9_-]{5,40}$")
_TT_ID = re.compile(r"^\d{8,25}$")
_SHORT_ID = re.compile(r"^[A-Za-z0-9_-]{4,20}$")


def _base_domain(host: str) -> str | None:
    for domain in ("youtube.com", "youtu.be", "instagram.com", "tiktok.com"):
        if host == domain or host.endswith("." + domain):
            return domain
    return None


def _not_supported() -> TranscriptionError:
    return TranscriptionError(
        "Only links to videos on YouTube, Instagram and TikTok are supported.",
        kind="link", title="This link isn't supported",
        hint="Use the Share button on a YouTube, Instagram or TikTok video, choose “Copy link” and paste it.")


def _not_a_video(what: str) -> TranscriptionError:
    return TranscriptionError(
        f"This link points to {what}, not to a single video.", kind="link", title="That's not a video",
        hint="Open the video itself, then use Share → Copy link.")


def clean_link(raw: str) -> str:
    """Return a safe, normalised https link to a single video, or raise a TranscriptionError."""
    url = (raw or "").strip()
    if not url:
        raise TranscriptionError("Paste a link to a video first.", kind="link", title="No link")
    if len(url) > MAX_LENGTH:
        raise TranscriptionError("This link is much longer than a normal video link.", kind="link",
                                 title="Link too long", hint="Copy the link again with the Share button.")
    if re.search(r"[\s\x00-\x1f\x7f<>\"'`\\]", url):
        raise TranscriptionError("The link contains spaces or characters that don't belong in a link.",
                                 kind="link", title="That's not a valid link",
                                 hint="Paste only the link itself, nothing before or after it.")
    if "://" not in url and re.match(r"^(www\.|m\.)?(youtube\.com|youtu\.be|instagram\.com|(vm\.|vt\.)?tiktok\.com)/", url, re.I):
        url = "https://" + url
    try:
        u = urlparse(url)
        port = u.port
    except ValueError as exc:
        raise TranscriptionError("This doesn't look like a valid link.", kind="link",
                                 title="That's not a valid link") from exc
    if u.scheme.lower() not in ("http", "https"):
        raise TranscriptionError("A video link starts with https://.", kind="link", title="That's not a web link",
                                 hint="Use the Share button on the video, choose “Copy link” and paste it here.")
    host = (u.hostname or "").lower().rstrip(".")
    if u.username or u.password or (port not in (None, 80, 443)) or not host:
        raise _not_supported()
    domain = _base_domain(host)
    if not domain:
        raise _not_supported()

    parts = [p for p in u.path.split("/") if p]
    query = parse_qs(u.query)
    keep: dict[str, str] = {}

    if domain == "youtube.com":
        if parts[:1] == ["watch"]:
            vid = (query.get("v") or [""])[0]
            if not _YT_ID.match(vid):
                raise _not_a_video("YouTube's home page or a playlist") if not vid else \
                    TranscriptionError("The video id in this link is incomplete.", kind="link",
                                       title="The link is incomplete", hint="Copy the full link again.")
            keep["v"] = vid
            path = "/watch"
        elif len(parts) >= 2 and parts[0] in ("shorts", "live", "embed", "v") and _YT_ID.match(parts[1]):
            path = f"/{parts[0]}/{parts[1]}"
        elif parts[:1] == ["playlist"]:
            raise _not_a_video("a playlist")
        elif parts and (parts[0].startswith("@") or parts[0] in ("channel", "c", "user")):
            raise _not_a_video("a YouTube channel")
        else:
            raise _not_a_video("a YouTube page")
        host = "www.youtube.com" if host not in ("music.youtube.com",) else host
    elif domain == "youtu.be":
        if not parts or not _YT_ID.match(parts[0]):
            raise _not_a_video("a YouTube page")
        path, host = f"/{parts[0]}", "youtu.be"
    elif domain == "instagram.com":
        for i, p in enumerate(parts[:-1]):
            if p in ("reel", "reels", "p", "tv") and _IG_ID.match(parts[i + 1]):
                path = f"/{p}/{parts[i + 1]}/"
                break
        else:
            if parts and parts[0] == "stories":
                raise _not_a_video("an Instagram story (stories aren't supported)")
            raise _not_a_video("an Instagram profile or page")
        host = "www.instagram.com"
    else:  # tiktok.com
        if host in ("vm.tiktok.com", "vt.tiktok.com"):
            if len(parts) != 1 or not _SHORT_ID.match(parts[0]):
                raise _not_a_video("a TikTok page")
            path = f"/{parts[0]}/"
        elif parts[:1] == ["t"] and len(parts) >= 2 and _SHORT_ID.match(parts[1]):
            path, host = f"/t/{parts[1]}/", "www.tiktok.com"
        elif "video" in parts[:-1] and _TT_ID.match(parts[parts.index("video") + 1]):
            i = parts.index("video")
            path, host = "/" + "/".join(parts[: i + 2]), "www.tiktok.com"
        elif "photo" in parts:
            raise _not_a_video("a TikTok photo post")
        else:
            raise _not_a_video("a TikTok profile or page")

    # No fragment (yt-dlp "smuggles" options through it), no tracking or playlist parameters.
    return urlunparse(("https", host, path, "", urlencode(keep), ""))
