import sys
import types

import pytest

from video_transcriptor import core
from video_transcriptor.models import Segment


class FakeYDL:
    """Stands in for yt_dlp.YoutubeDL; records what happened."""

    info: dict = {}
    downloaded = False
    tmpdirs: list = []

    def __init__(self, opts):
        self.opts = opts
        FakeYDL.tmpdirs.append(opts["outtmpl"].rsplit("/", 1)[0])

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        return dict(FakeYDL.info)

    def process_ie_result(self, info, download=True):
        FakeYDL.downloaded = True
        with open(self.opts["outtmpl"].replace("%(ext)s", "m4a"), "wb") as f:
            f.write(b"fake audio")

    def urlopen(self, url):
        return types.SimpleNamespace(read=lambda: b"WEBVTT\n\n00:00.000 --> 00:01.000\nfrom captions\n")


@pytest.fixture
def fake_ytdlp(monkeypatch):
    class DownloadError(Exception):
        pass

    module = types.SimpleNamespace(YoutubeDL=FakeYDL, utils=types.SimpleNamespace(DownloadError=DownloadError))
    monkeypatch.setitem(sys.modules, "yt_dlp", module)
    import numpy as np

    monkeypatch.setattr(core.sandbox, "decode_audio", lambda path, max_s, workdir=None, cancel=None: np.zeros(16000 * 30, "float32"))
    FakeYDL.info, FakeYDL.downloaded, FakeYDL.tmpdirs = {}, False, []
    calls = []

    def fake_asr(path, model, language, device, on_progress=None):
        calls.append((model, language))
        return [Segment(0, 1, "from speech")], language or "en", 30.0

    monkeypatch.setattr(core.asr, "transcribe_file", fake_asr)
    return calls


def test_rejects_videos_longer_than_limit(fake_ytdlp):
    FakeYDL.info = {"title": "long", "duration": core.MAX_DURATION_SECONDS + 1}
    with pytest.raises(core.TranscriptionError, match="limit is 10 minutes"):
        core.transcribe("https://www.youtube.com/watch?v=abcdefghijk")
    assert not FakeYDL.downloaded


def test_uses_captions_without_downloading(fake_ytdlp):
    FakeYDL.info = {"title": "t", "duration": 30, "language": "en",
                    "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/en.vtt"}]}}
    t = core.transcribe("https://www.youtube.com/watch?v=abcdefghijk")
    assert t.source == "captions" and t.text == "from captions"
    assert not FakeYDL.downloaded and not fake_ytdlp


def test_falls_back_to_speech_recognition_and_cleans_up(fake_ytdlp):
    import os

    FakeYDL.info = {"title": "reel", "duration": 30}
    t = core.transcribe("https://www.instagram.com/reel/ABCDEFGH/")
    assert t.source == "speech-recognition" and t.text == "from speech"
    assert fake_ytdlp == [("small.en", "en")]  # English-first defaults
    assert FakeYDL.downloaded
    assert not any(os.path.exists(d) for d in FakeYDL.tmpdirs)


def test_other_language_gets_multilingual_model(fake_ytdlp):
    FakeYDL.info = {"title": "reel", "duration": 30}
    core.transcribe("https://www.instagram.com/reel/ABCDEFGH/", language="nl", use_captions=False)
    assert fake_ytdlp == [("large-v3-turbo", "nl")]


def test_english_only_model_rejects_other_language():
    with pytest.raises(core.TranscriptionError, match="only understands English"):
        core.transcribe("https://www.instagram.com/reel/ABCDEFGH/", language="nl", model="small.en")


def test_rejects_things_that_are_not_links_or_files():
    with pytest.raises(core.TranscriptionError, match="not a web link"):
        core.transcribe("not a link")
    with pytest.raises(core.TranscriptionError, match="no model called"):
        core.transcribe("https://www.youtube.com/watch?v=abcdefghijk", model="gpt")


def test_windows_firefox_profile_is_found_under_wsl(tmp_path, monkeypatch):
    import os

    monkeypatch.setattr(core.Path, "home", lambda: tmp_path / "home")
    old = tmp_path / "Users/me/AppData/Roaming/Mozilla/Firefox/Profiles/old.default"
    new = tmp_path / "Users/me/AppData/Roaming/Mozilla/Firefox/Profiles/new.default-release"
    for i, profile in enumerate((old, new)):
        profile.mkdir(parents=True)
        (profile / "cookies.sqlite").write_bytes(b"")
        os.utime(profile / "cookies.sqlite", (1000 + i, 1000 + i))
    assert core._windows_firefox_profile(tmp_path / "Users") == str(new)
    assert core._windows_firefox_profile(tmp_path / "nope") is None


def test_cookie_options():
    opts = core._ydl_options("chrome:Profile 1", None)
    assert opts["cookiesfrombrowser"] == ("chrome", "Profile 1")


def test_switches_to_multilingual_model_when_youtube_says_the_video_is_not_english(fake_ytdlp):
    FakeYDL.info = {"title": "nl video", "duration": 30, "language": "nl"}
    t = core.transcribe("https://www.youtube.com/watch?v=abcdefghijk", use_captions=False)
    assert fake_ytdlp == [("large-v3-turbo", "nl")]
    assert t.extra["switched_from_model"] == "small.en"
