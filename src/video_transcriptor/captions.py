"""Pick and parse captions that the platform already provides (no audio needed)."""

from __future__ import annotations

import html
import json
import re

from .models import Segment

# Preferred subtitle formats, best first.
_PREFERRED_EXTS = ("json3", "vtt")


def _match(tracks: dict, lang: str) -> str | None:
    """Return the track key for `lang` (exact, '<lang>-orig', or a regional variant)."""
    if not tracks:
        return None
    for key in (f"{lang}-orig", lang):
        if key in tracks:
            return key
    for key in tracks:
        if key.split("-")[0] == lang and "-" in key:
            return key
    return None


def choose_track(info: dict, language: str | None = None,
                 allow_auto: bool = False) -> tuple[str, dict, bool] | None:
    """Pick the caption track that matches the spoken language.

    Returns (language, format entry, is_automatic) or None when no suitable track exists.
    By default only captions made by the uploader are used: the platform's automatic
    captions have little or no punctuation, and Whisper does better. With `allow_auto`,
    only the original-language auto track is acceptable (the others are machine-translated).
    """
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if k != "live_chat"}
    auto = (info.get("automatic_captions") or {}) if allow_auto else {}
    lang = language or info.get("language")

    candidates: list[tuple[str, dict, bool]] = []
    if lang:
        if key := _match(manual, lang):
            candidates.append((key, manual, False))
        if key := _match(auto, lang):
            candidates.append((key, auto, True))
    elif orig := [k for k in auto if k.endswith("-orig")]:
        candidates.append((orig[0], auto, True))
    elif len(manual) == 1:
        candidates.append((next(iter(manual)), manual, False))

    for key, tracks, is_auto in candidates:
        formats = {f.get("ext"): f for f in tracks[key] if f.get("url")}
        for ext in _PREFERRED_EXTS:
            if ext in formats:
                return key.removesuffix("-orig"), formats[ext], is_auto
    return None


def parse_json3(data: str) -> list[Segment]:
    """Parse YouTube's json3 caption format."""
    segments = []
    for event in json.loads(data).get("events", []):
        text = "".join(s.get("utf8", "") for s in event.get("segs") or [])
        text = " ".join(text.split())
        if not text:
            continue
        start = event.get("tStartMs", 0) / 1000
        end = start + event.get("dDurationMs", 0) / 1000
        segments.append(Segment(start, end, text))
    return _merge_short(segments)


_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")


def _parse_time(value: str) -> float:
    m = _TIME.search(value)
    if not m:
        raise ValueError(f"Bad timestamp: {value!r}")
    h, mnt, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(s) + int(ms) / 1000


def parse_vtt(data: str) -> list[Segment]:
    """Parse WebVTT, removing styling tags and the repeated lines of 'rolling' auto-captions."""
    segments: list[Segment] = []
    last_line = None
    for block in re.split(r"\r?\n\s*\r?\n", data):
        lines = block.strip().splitlines()
        idx = next((i for i, line in enumerate(lines) if "-->" in line), None)
        if idx is None:
            continue
        start_s, end_s = lines[idx].split("-->")[:2]
        start, end = _parse_time(start_s), _parse_time(end_s)
        new_lines = []
        for raw in lines[idx + 1 :]:
            line = " ".join(html.unescape(re.sub(r"<[^>]+>", "", raw)).split())
            if line and line != last_line:
                new_lines.append(line)
                last_line = line
        if new_lines:
            segments.append(Segment(start, end, " ".join(new_lines)))
    return _merge_short(segments)


def _merge_short(segments: list[Segment], min_chars: int = 40, max_chars: int = 120) -> list[Segment]:
    """Join tiny caption fragments into readable lines."""
    merged: list[Segment] = []
    for seg in segments:
        if merged and len(merged[-1].text) < min_chars and len(merged[-1].text) + len(seg.text) < max_chars:
            prev = merged[-1]
            merged[-1] = Segment(prev.start, max(prev.end, seg.end), f"{prev.text} {seg.text}")
        else:
            merged.append(seg)
    return merged


def parse(data: str, ext: str) -> list[Segment]:
    return parse_json3(data) if ext == "json3" else parse_vtt(data)
