import json

import pytest

from video_transcriptor import formats
from video_transcriptor.models import Segment, Transcript

T = Transcript(
    [Segment(0.0, 1.5, "Hello there."), Segment(3661.25, 3662.0, "One hour later.")],
    language="en", source="captions", title="Demo",
)


def test_txt():
    assert formats.to_txt(T) == "Hello there. One hour later.\n"


def test_srt():
    assert formats.to_srt(T) == (
        "1\n00:00:00,000 --> 00:00:01,500\nHello there.\n\n"
        "2\n01:01:01,250 --> 01:01:02,000\nOne hour later.\n"
    )


def test_vtt():
    out = formats.to_vtt(T)
    assert out.startswith("WEBVTT\n")
    assert "01:01:01.250 --> 01:01:02.000" in out


def test_json_round_trip():
    data = json.loads(formats.to_json(T))
    assert data["text"] == "Hello there. One hour later."
    assert data["segments"][1]["start"] == 3661.25


def test_unknown_format():
    with pytest.raises(ValueError):
        formats.render(T, "docx")
