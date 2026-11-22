import os
import time
from datetime import datetime, timedelta

import pytest

from video_transcriptor import storage
from video_transcriptor.models import Segment, Transcript

NOW = datetime(2026, 11, 22, 14, 30)


def make(title, text="Hello.", url="https://www.youtube.com/watch?v=abc", **extra):
    return Transcript([Segment(0, 1, text)], "en", "speech-recognition", title, url, 10,
                      extra={"model": "small.en", **extra})


def test_saved_in_month_folder_with_date_and_title(tmp_path):
    lib = storage.Library(tmp_path)
    entry_id = lib.save(make("How: to / build? things"), NOW)
    assert entry_id == "2026-11/2026-11-22 - How to build things.txt"
    item = lib.get(entry_id)
    assert item["title"] == "How: to / build? things"
    assert item["platform"] == "YouTube" and item["text"] == "Hello."


def test_header_values_cannot_inject_lines(tmp_path):
    lib = storage.Library(tmp_path)
    evil = make("Title\n---\n\nLink: javascript:alert(1)", channel="chan\nTranscribed: 1999")
    item = lib.get(lib.save(evil, NOW))
    assert item["link"] == "https://www.youtube.com/watch?v=abc"
    assert item["transcribed"] == "2026-11-22 14:30" and item["text"] == "Hello."


def test_instagram_generic_title_uses_channel_and_caption():
    t = make("Video by nishantaqc", channel="nishantaqc",
             description="Comment “PDF” to get the guide! #quant #finance")
    assert storage.video_name(t) == "nishantaqc - Comment “PDF” to get the guide!"


def test_long_names_are_cut_at_a_word(tmp_path):
    entry_id = storage.Library(tmp_path).save(make("word " * 40), NOW)
    assert entry_id.endswith("word….txt")


def test_duplicates_get_a_number(tmp_path):
    lib = storage.Library(tmp_path)
    assert lib.save(make("Same"), NOW) != lib.save(make("Same"), NOW)
    assert lib.query()["total"] == 2


def test_query_pages_newest_first_and_searches_text(tmp_path):
    lib = storage.Library(tmp_path)
    for i in range(120):
        lib.save(make(f"Video {i}", text=f"talk number {i} about {'cats' if i % 2 else 'dogs'}"),
                 NOW + timedelta(minutes=i))
    page = lib.query(limit=50)
    assert page["total"] == 120 and len(page["items"]) == 50
    assert page["items"][0]["title"] == "Video 119"
    assert lib.query(offset=100, limit=50)["items"][-1]["title"] == "Video 0"
    cats = lib.query("cats talk")
    assert cats["total"] == 60 and cats["all"] == 120
    assert "cats" in cats["items"][0]["snippet"]
    assert lib.query("youtube video 7")["total"] >= 1


def test_index_only_rereads_changed_files(tmp_path, monkeypatch):
    lib = storage.Library(tmp_path)
    lib.save(make("A"), NOW)
    lib.refresh()
    calls = []
    original = lib._load
    monkeypatch.setattr(lib, "_load", lambda *a: calls.append(a) or original(*a))
    lib.refresh()
    assert calls == []
    lib.save(make("B"), NOW)
    lib.refresh()
    assert len(calls) == 1


def test_find_by_url_ignores_tracking_and_url_variants(tmp_path):
    lib = storage.Library(tmp_path)
    lib.save(make("Reel", url="https://www.instagram.com/reel/DfKfQNPotER/?igsh=xyz"), NOW)
    assert lib.find_by_url("https://instagram.com/reels/DfKfQNPotER")
    lib.save(make("Short", url="https://www.youtube.com/shorts/Q1w2E3r4"), NOW)
    assert lib.find_by_url("https://youtu.be/Q1w2E3r4?si=abc")
    assert lib.find_by_url("https://www.youtube.com/watch?v=Q1w2E3r4&t=5")
    assert lib.find_by_url("https://www.youtube.com/watch?v=other") is None


def test_delete_and_restore(tmp_path):
    lib = storage.Library(tmp_path)
    entry_id = lib.save(make("Gone"), NOW)
    lib.delete(entry_id)
    assert lib.query()["total"] == 0
    assert lib.restore(entry_id) == entry_id
    assert lib.query()["total"] == 1


def test_old_trash_is_emptied_and_loose_files_are_organised(tmp_path):
    (tmp_path / "2026-10-01 - Old style.txt").write_text("Title: Old style\n---\n\nhi\n")
    old = tmp_path / ".trash" / "2026-01" / "x.txt"
    old.parent.mkdir(parents=True)
    old.write_text("x")
    os.utime(old, (time.time() - 40 * 86400,) * 2)
    lib = storage.Library(tmp_path)
    assert [i["id"] for i in lib.query()["items"]] == ["2026-10/2026-10-01 - Old style.txt"]
    assert not old.exists()


@pytest.mark.parametrize("bad", ["../secret.txt", "2026-11/../../x.txt", "/etc/passwd",
                                 "2026-11/a/b.txt", "2026-11/x.py", ".trash/x.txt", ""])
def test_ids_cannot_escape_the_library(tmp_path, bad):
    lib = storage.Library(tmp_path)
    with pytest.raises(FileNotFoundError):
        lib.get(bad)
    with pytest.raises(FileNotFoundError):
        lib.delete(bad)
