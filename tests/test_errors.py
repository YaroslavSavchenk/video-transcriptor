"""Real yt-dlp error messages (collected from yt-dlp 2026.10) map to clear user errors."""

import pytest

from video_transcriptor.errors import classify_download_error

YT, IG, TT = "https://www.youtube.com/watch?v=x", "https://www.instagram.com/reel/x/", "https://www.tiktok.com/@a/video/1"


class FakeHTTPError(Exception):
    def __init__(self, status):
        self.status = status


class UnsupportedError(Exception):
    pass


class DownloadError(Exception):
    def __init__(self, msg, original=None):
        super().__init__(msg)
        self.exc_info = (type(original), original, None) if original else None


@pytest.mark.parametrize("msg,url,kind,title", [
    ("ERROR: Unsupported URL: https://example.com/", "https://example.com/", "link", "This link isn't supported"),
    ("ERROR: [youtube] aaaaaaaaaa: Incomplete YouTube ID aaaaaaaaaa. URL looks truncated.", YT, "link", "The link is incomplete"),
    ("ERROR: [Instagram] x: There is no video in this post", IG, "link", "That's not a video"),
    ("ERROR: [youtube] x: Video unavailable. This video is unavailable", YT, "video", "Video not found"),
    ("ERROR: [youtube] x: Video unavailable. This video has been removed for violating YouTube's policy", YT, "video", "Video not found"),
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video", YT, "video", "This video is private"),
    ("ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate for some users.", YT, "video", "Age-restricted video"),
    ("ERROR: [youtube] x: The uploader has not made this video available in your country", YT, "video", "Not available in your country"),
    ("ERROR: [youtube] x: This live event will begin in 3 hours.", YT, "video", "Live stream"),
    ("ERROR: [Instagram] x: Instagram sent an empty media response. Check if this post is accessible in your browser without being logged-in. If it is not, then use --cookies-from-browser or --cookies for the authentication.", IG, "platform", "Instagram didn't share this video"),
    ("ERROR: [Instagram] AAAAAAAAAAA: Video info extraction failed: HTTP Error 400: Bad Request (caused by <HTTPError 400: Bad Request>)", IG, "platform", "Instagram didn't share this video"),
    ("ERROR: [TikTok] 1: Unexpected response from webpage request; please report this issue on https://github.com/yt-dlp/yt-dlp/issues", TT, "platform", "TikTok changed something"),
    ("ERROR: [TikTok] 1: Your IP address is blocked from accessing this post", TT, "platform", "TikTok blocks this video for your connection"),
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser", YT, "platform", "YouTube is limiting requests"),
    ("ERROR: [generic] Unable to download webpage: [Errno -2] Name or service not known", "https://nope.invalid/v", "network", "No connection"),
    ("ERROR: something totally new happened", YT, "app", "Couldn't get this video"),
])
def test_real_messages(msg, url, kind, title):
    err = classify_download_error(DownloadError(msg), url, cookies_enabled=True)
    assert (err.kind, err.title) == (kind, title)
    assert err.hint and err.message
    assert "please report" not in (err.technical or "").lower()


def test_exception_types_win_over_wording():
    assert classify_download_error(DownloadError("ERROR: x", UnsupportedError()), YT).kind == "link"
    assert classify_download_error(DownloadError("ERROR: x", FakeHTTPError(404)), YT).title == "Video not found"
    assert classify_download_error(DownloadError("ERROR: x", FakeHTTPError(429)), YT).kind == "platform"


def test_login_hint_depends_on_cookie_setting():
    msg = "ERROR: [Instagram] x: Instagram sent an empty media response."
    assert "Firefox" in classify_download_error(DownloadError(msg), IG, cookies_enabled=True).hint
    assert "--cookies-from-browser" in classify_download_error(DownloadError(msg), IG, cookies_enabled=False).hint
