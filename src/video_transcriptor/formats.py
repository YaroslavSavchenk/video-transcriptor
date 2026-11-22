"""Render a transcript as plain text, SRT, WebVTT or JSON."""

from __future__ import annotations

import json

from .models import Transcript

FORMATS = ("txt", "srt", "vtt", "json")


def _timestamp(seconds: float, sep: str) -> str:
    ms = max(0, round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_txt(t: Transcript) -> str:
    return t.text + "\n"


def to_srt(t: Transcript) -> str:
    blocks = []
    for i, seg in enumerate((s for s in t.segments if s.text), start=1):
        blocks.append(f"{i}\n{_timestamp(seg.start, ',')} --> {_timestamp(seg.end, ',')}\n{seg.text}\n")
    return "\n".join(blocks)


def to_vtt(t: Transcript) -> str:
    blocks = ["WEBVTT\n"]
    for seg in t.segments:
        if seg.text:
            blocks.append(f"{_timestamp(seg.start, '.')} --> {_timestamp(seg.end, '.')}\n{seg.text}\n")
    return "\n".join(blocks)


def to_json(t: Transcript) -> str:
    return json.dumps(t.to_dict(), ensure_ascii=False, indent=2) + "\n"


def render(t: Transcript, fmt: str) -> str:
    renderers = {"txt": to_txt, "srt": to_srt, "vtt": to_vtt, "json": to_json}
    if fmt not in renderers:
        raise ValueError(f"Unknown format {fmt!r}; choose from {', '.join(FORMATS)}")
    return renderers[fmt](t)
