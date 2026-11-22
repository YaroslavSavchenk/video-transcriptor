from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    segments: list[Segment]
    language: str | None
    source: str  # "captions" or "speech-recognition"
    title: str | None = None
    url: str | None = None
    duration: float | None = None
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segments if s.text).strip()

    def to_dict(self) -> dict:
        data = asdict(self)
        data["text"] = self.text
        return data
