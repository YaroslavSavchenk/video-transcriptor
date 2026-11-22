from datetime import datetime

import pytest

from video_transcriptor import storage
from video_transcriptor.models import Segment, Transcript

NOW = datetime(2026, 11, 22, 14, 30)


def make(title, **extra):
    return Transcript([Segment(0, 1, "Hello.")], "en", "speech-recognition", title,
                      "https://example.com/v", 10, extra={"model": "small.en", **extra})


def test_filename_has_date_and_video_title(tmp_path):
    path = storage.save(make("How: to / build? things"), tmp_path, NOW)
    assert path.name == "2026-11-22 - How to build things.txt"
    content = path.read_text()
    assert "Title: How: to / build? things" in content and content.rstrip().endswith("Hello.")


def test_instagram_generic_title_uses_channel_and_caption(tmp_path):
    t = make("Video by nishantaqc", channel="nishantaqc",
             description="Comment “PDF” to get the guide! #quant #finance")
    assert storage.video_name(t) == "nishantaqc - Comment “PDF” to get the guide!"


def test_duplicates_get_a_number(tmp_path):
    first = storage.save(make("Same"), tmp_path, NOW)
    second = storage.save(make("Same"), tmp_path, NOW)
    assert second.name == "2026-11-22 - Same (2).txt" and first != second


def test_read_saved_and_reject_paths(tmp_path):
    path = storage.save(make("Title"), tmp_path, NOW)
    item = storage.read_saved(tmp_path, path.name)
    assert item["meta"]["language"] == "en" and item["text"] == "Hello."
    assert storage.list_saved(tmp_path)[0]["file"] == path.name
    with pytest.raises(FileNotFoundError):
        storage.read_saved(tmp_path, "../secret.txt")


def test_long_names_are_cut_at_a_word(tmp_path):
    path = storage.save(make("word " * 40), tmp_path, NOW)
    assert path.stem.endswith("word…") and len(path.stem) <= 13 + 81
