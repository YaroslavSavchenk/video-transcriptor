"""User-facing errors: what went wrong, whose side it's on, and what to do about it.

Every error the app shows has a *kind* that tells the user where the problem is:

    link      the link itself (not a video link, unsupported site, typo)
    video     this particular video (removed, private, too long, silent, region-locked)
    platform  YouTube/Instagram/TikTok refused or changed something (blocking, login wall)
    network   the internet connection
    settings  a combination of options that can't work
    app       a bug or broken component in the app itself
"""

from __future__ import annotations

import re

KINDS = ("link", "video", "platform", "network", "settings", "app")

_REPORT_NOISE = re.compile(
    r"\s*(;\s*)?please report this issue.*$|\s*Confirm you are on the latest version.*$",
    re.IGNORECASE | re.DOTALL,
)


class TranscriptionError(Exception):
    """An error with a message that is safe and useful to show to the user."""

    def __init__(self, message: str, *, kind: str = "app", title: str | None = None,
                 hint: str | None = None, technical: str | None = None):
        super().__init__(message)
        self.kind = kind if kind in KINDS else "app"
        self.title = title or "Something went wrong"
        self.message = message
        self.hint = hint
        self.technical = technical

    def to_dict(self) -> dict:
        return {"kind": self.kind, "title": self.title, "message": self.message,
                "hint": self.hint, "technical": self.technical}


def _clean(msg: str) -> str:
    msg = msg.removeprefix("ERROR: ").strip()
    return _REPORT_NOISE.sub("", msg).strip()


def _platform(url: str) -> str:
    u = url.lower()
    if "instagram.com" in u:
        return "Instagram"
    if "tiktok.com" in u:
        return "TikTok"
    if "youtube.com" in u or "youtu.be" in u:
        return "YouTube"
    return "the website"


def _login_hint(platform: str, cookies_enabled: bool) -> str:
    if cookies_enabled:
        return (f"Open the link in Firefox. If you can watch it there, log in to {platform} in Firefox "
                "(the app uses Firefox's login) and try again.")
    return ("Start the tool with --cookies-from-browser firefox (and log in to "
            f"{platform} in Firefox), then try again.")


def classify_download_error(exc: Exception, url: str, cookies_enabled: bool = False) -> TranscriptionError:
    """Turn a yt-dlp error into a clear message. Checks exception types first, then wording."""
    technical = _clean(str(exc))
    low = technical.lower()
    platform = _platform(url)
    original = getattr(exc, "exc_info", None)
    original = original[1] if original and len(original) > 1 else None
    type_name = type(original).__name__ if original else ""
    status = getattr(original, "status", None) or getattr(getattr(original, "response", None), "status", None)

    def err(kind, title, message, hint=None):
        return TranscriptionError(message, kind=kind, title=title, hint=hint, technical=technical)

    # --- the link itself
    if type_name == "UnsupportedError" or "unsupported url" in low or "is not a valid url" in low:
        return err("link", "This link isn't supported",
                   "This isn't a link to a YouTube, Instagram or TikTok video.",
                   "Use the Share button on the video and choose “Copy link”, then paste that link.")
    if "incomplete youtube id" in low or "looks truncated" in low:
        return err("link", "The link is incomplete",
                   "Part of the link seems to be missing.",
                   "Copy the full link again with the Share button and paste it.")
    if ("there is no video in this post" in low or "does not have any videos" in low):
        return err("link", "That's not a video",
                   "This link points to a photo post or a profile, not to a video.",
                   "Open the video itself and copy its link.")

    # --- this particular video
    if type_name == "GeoRestrictedError" or "not available in your country" in low \
            or "geo restriction" in low or "available in your country" in low:
        return err("video", "Not available in your country",
                   f"{platform} doesn't show this video in your region.",
                   "Try another video, or use a VPN if you're allowed to.")
    if "private video" in low or "account is private" in low \
            or "do not have permission to view" in low or "only available for registered users who follow" in low:
        return err("video", "This video is private",
                   "Only certain accounts are allowed to watch this video.",
                   _login_hint(platform, cookies_enabled))
    if "members-only" in low or "join this channel" in low or "members only" in low:
        return err("video", "Members-only video",
                   "This video is only for paying channel members.",
                   "Pick another video, or log in with an account that has access.")
    if "sign in to confirm your age" in low or "age-restricted" in low or "inappropriate for some users" in low:
        return err("video", "Age-restricted video",
                   f"{platform} only shows this video to logged-in adults.",
                   _login_hint(platform, cookies_enabled))
    if any(s in low for s in ("live event will begin", "premieres in", "is live", "livestream",
                              "live stream recording is not available", "this live event")):
        return err("video", "Live stream",
                   "Live streams and premieres can't be transcribed while they're live.",
                   "Wait until the recording is published, then try again.")
    if status == 404 or "http error 404" in low or any(s in low for s in (
            "video unavailable", "this video is unavailable", "has been removed", "does not exist",
            "has been terminated", "video not available", "post isn't available", "not found.")):
        return err("video", "Video not found",
                   "This video was deleted, made unavailable, or the link is wrong.",
                   "Check that the link opens in your browser.")
    if "drm" in low:
        return err("video", "Protected video",
                   "This video is copy-protected (DRM) and can't be transcribed.", "Try another video.")

    # --- the platform refused
    if "empty media response" in low or (platform == "Instagram" and (
            "http error 400" in low or "info extraction failed" in low or status == 400)):
        return err("platform", "Instagram didn't share this video",
                   "Instagram refused to give out this video. It may be private or deleted, "
                   "or Instagram wants you to be logged in.",
                   _login_hint("Instagram", cookies_enabled))
    if status == 429 or any(s in low for s in ("rate-limit", "rate limit", "too many requests", "captcha",
                                               "not a bot", "http error 429")):
        return err("platform", f"{platform} is limiting requests",
                   f"{platform} thinks too many requests came from your connection.",
                   "Wait 10–30 minutes and try again. " + _login_hint(platform, cookies_enabled))
    if "ip address is blocked" in low:
        return err("platform", f"{platform} blocks this video for your connection",
                   f"{platform} doesn't allow this video to be downloaded from your network.",
                   "Try another video, or try again later or from another network.")
    if any(s in low for s in ("unexpected response from webpage request", "unable to extract challenge",
                              "failed to parse json", "unable to extract")):
        return err("platform", f"{platform} changed something",
                   f"{platform} answered in a way the downloader doesn't understand. This usually means "
                   f"{platform} changed its website.",
                   "Update the app (scripts/update.sh) and try again. If it still fails, try again later.")
    if any(s in low for s in ("login required", "requiring login", "log in for access", "redirected to the login",
                              "only available for registered users", "use --cookies", "sign in")):
        return err("platform", "Login required",
                   f"{platform} only shows this video to logged-in users.",
                   _login_hint(platform, cookies_enabled))
    if status == 403 or "http error 403" in low:
        return err("platform", "Access denied",
                   f"{platform} refused access to this video.",
                   _login_hint(platform, cookies_enabled))

    # --- the connection
    if type_name in ("TransportError", "ProxyError", "SSLError", "ConnectionError") or any(s in low for s in (
            "failed to resolve", "name or service not known", "temporary failure in name resolution",
            "timed out", "network is unreachable", "connection refused", "connection reset",
            "unable to connect to proxy", "getaddrinfo failed", "no route to host")):
        return err("network", "No connection",
                   f"Couldn't reach {platform}.",
                   "Check your internet connection (and VPN or proxy), then try again.")

    # --- anything else: probably a broken or outdated downloader
    return err("app", "Couldn't get this video",
               "The downloader ran into a problem it doesn't recognise.",
               "Check that the link works in your browser. If it does, update the app "
               "(scripts/update.sh) and try again.")


class Cancelled(Exception):
    """The user cancelled the transcription. Not an error: nothing to show."""
