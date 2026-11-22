import json

from video_transcriptor import captions

ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
hello<00:00:00.500><c> world</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
hello world

00:00:02.010 --> 00:00:04.000 align:start position:0%
hello world
how<00:00:02.500><c> are</c><00:00:03.000><c> you</c>
"""


def test_parse_vtt_removes_tags_and_rolling_duplicates():
    segs = captions.parse_vtt(ROLLING_VTT)
    assert " ".join(s.text for s in segs) == "hello world how are you"
    assert segs[0].start == 0.0
    assert segs[-1].end == 4.0


def test_parse_vtt_handles_short_timestamps_and_entities():
    data = "WEBVTT\n\n00:01.000 --> 00:02.500\nTom &amp; Jerry\n"
    segs = captions.parse_vtt(data)
    assert segs[0].text == "Tom & Jerry"
    assert (segs[0].start, segs[0].end) == (1.0, 2.5)


def test_parse_json3():
    data = json.dumps({"events": [
        {"tStartMs": 0, "dDurationMs": 1500, "segs": [{"utf8": "Hello"}, {"utf8": " there"}]},
        {"tStartMs": 1500, "dDurationMs": 10, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 2000, "dDurationMs": 1000},
    ]})
    segs = captions.parse_json3(data)
    assert [s.text for s in segs] == ["Hello there"]
    assert segs[0].end == 1.5


def _fmt(ext):
    return {"ext": ext, "url": f"https://example.com/{ext}"}


def test_choose_track_prefers_original_auto_caption_over_translations():
    info = {"language": None, "subtitles": {},
            "automatic_captions": {"de": [_fmt("vtt")], "en-orig": [_fmt("vtt"), _fmt("json3")], "en": [_fmt("vtt")]}}
    lang, fmt, is_auto = captions.choose_track(info)
    assert (lang, fmt["ext"], is_auto) == ("en", "json3", True)


def test_choose_track_prefers_manual_subtitles_in_requested_language():
    info = {"subtitles": {"en": [_fmt("vtt")], "de": [_fmt("vtt")]},
            "automatic_captions": {"en-orig": [_fmt("json3")]}}
    assert captions.choose_track(info, "en")[2] is False


def test_choose_track_skips_ambiguous_or_missing_tracks():
    assert captions.choose_track({}) is None
    assert captions.choose_track({"subtitles": {"en": [_fmt("vtt")], "de": [_fmt("vtt")]}}) is None
    assert captions.choose_track({"subtitles": {"nl": [_fmt("vtt")]}}, "en") is None
    assert captions.choose_track({"subtitles": {"en": [_fmt("srv1")]}}, "en") is None
