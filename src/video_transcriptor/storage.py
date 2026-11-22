"""The transcript library: every transcript is a plain .txt file, organised per month.

Layout (inside the app folder by default):

    transcripts/
      2026-11/
        2026-11-22 - The science of laughter - Sasha Winkler.txt
      .trash/            deleted transcripts, kept 30 days so a delete can be undone

Each file starts with a small header (title, link, date, ...) followed by the text, so the
files stay readable and searchable without the app. The app keeps an in-memory index that is
refreshed incrementally (only new or changed files are read), which keeps listing and
searching fast with thousands of transcripts.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .models import Transcript

_GENERIC_TITLE = re.compile(r"^(video|reel|post) by \S+$", re.IGNORECASE)
_HEADER_END = "\n---\n\n"
_MONTH_DIR = re.compile(r"^\d{4}-\d{2}$")
_ID = re.compile(r"^(\d{4}-\d{2})/([^/\\\x00-\x1f]+\.txt)$")
_TRASH = ".trash"
TRASH_DAYS = 30


def is_wsl() -> bool:
    return "microsoft" in os.uname().release.lower() if hasattr(os, "uname") else False


def default_dir() -> Path:
    """Transcripts live with the app: `<project folder>/transcripts`.

    When installed as a regular package (no project folder), fall back to the user's data folder.
    """
    project = Path(__file__).resolve().parents[2]
    if (project / "pyproject.toml").is_file():
        return project / "transcripts"
    data_home = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return data_home / "video-transcriptor" / "transcripts"


# --------------------------------------------------------------------------- naming


def _one_line(value: str) -> str:
    """Collapse whitespace and control characters, so values can't break the file header."""
    return " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(value)).split())


def video_name(t: Transcript) -> str:
    """A human name for the video. Instagram titles are just 'Video by <user>', so use the caption."""
    title = _one_line(t.title or "")
    channel = t.extra.get("channel")
    if not title or _GENERIC_TITLE.match(title):
        caption = _one_line(t.extra.get("description") or "")
        caption = re.split(r"(?<=[.!?])\s|#", caption)[0].strip() if caption else ""
        title = f"{channel} - {caption}" if channel and caption else (caption or title or "transcript")
    return title


def _safe_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]+', " ", name)  # characters Windows doesn't allow
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > max_len:
        cut = name[:max_len]
        name = (cut.rsplit(" ", 1)[0] if " " in cut[max_len // 2:] else cut) + "…"
    return name.rstrip(" .") or "transcript"


def platform_of(url: str | None) -> str | None:
    host = (urlparse(url or "").hostname or "").lower()
    for domain, name in (("youtube.com", "YouTube"), ("youtu.be", "YouTube"),
                         ("instagram.com", "Instagram"), ("tiktok.com", "TikTok")):
        if host == domain or host.endswith("." + domain):
            return name
    return host.removeprefix("www.") or None


def url_key(url: str | None) -> str | None:
    """A stable key for 'the same video', ignoring tracking parameters and URL variants."""
    if not url:
        return None
    u = urlparse(url.strip())
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    parts = [p for p in u.path.split("/") if p]
    if host in ("youtube.com", "music.youtube.com"):
        if parts[:1] == ["watch"] and (v := parse_qs(u.query).get("v")):
            return f"youtube:{v[0]}"
        if len(parts) >= 2 and parts[0] in ("shorts", "live", "embed"):
            return f"youtube:{parts[1]}"
    if host == "youtu.be" and parts:
        return f"youtube:{parts[0]}"
    if host == "instagram.com":
        for i, p in enumerate(parts[:-1]):
            if p in ("reel", "reels", "p", "tv"):
                return f"instagram:{parts[i + 1]}"
    if host.endswith("tiktok.com") and "video" in parts[:-1]:
        return f"tiktok:{parts[parts.index('video') + 1]}"
    return f"{host}/{'/'.join(parts)}".lower()


# --------------------------------------------------------------------------- library


@dataclass
class Entry:
    id: str
    title: str
    link: str | None
    key: str | None
    transcribed: str  # "YYYY-MM-DD HH:MM"
    language: str | None
    source: str | None
    platform: str | None
    channel: str | None
    text: str
    mtime: int
    haystack: str  # lower-case text used for searching

    def summary(self) -> dict:
        return {"id": self.id, "title": self.title, "transcribed": self.transcribed,
                "platform": self.platform, "channel": self.channel}

    def full(self) -> dict:
        return {**self.summary(), "link": self.link, "language": self.language,
                "source": self.source, "text": self.text}


def _parse(raw: str) -> tuple[dict, str]:
    header, sep, text = raw.partition(_HEADER_END)
    if not sep:
        return {}, raw.strip()
    meta = {}
    for line in header.splitlines():
        key, _, value = line.partition(": ")
        meta[key.strip().lower()] = value.strip()
    return meta, text.strip()


def _snippet(text: str, terms: list[str], width: int = 70) -> str:
    lower = text.lower()
    pos = min((p for t in terms if (p := lower.find(t)) >= 0), default=-1)
    if pos < 0:
        return text[: width * 2] + ("…" if len(text) > width * 2 else "")
    start, end = max(0, pos - width), min(len(text), pos + width)
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


class Library:
    def __init__(self, root: Path):
        self.root = root
        self._index: dict[str, Entry] = {}
        self._lock = threading.Lock()
        self._organise()

    # -- housekeeping

    def _organise(self) -> None:
        """Move loose files from older versions into month folders and empty the old trash."""
        if not self.root.is_dir():
            return
        for path in self.root.glob("*.txt"):
            m = re.match(r"^(\d{4}-\d{2})-\d{2} - ", path.name)
            month = m.group(1) if m else datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m")
            (self.root / month).mkdir(exist_ok=True)
            path.rename(self._free_path(self.root / month, path.stem))
        trash = self.root / _TRASH
        if trash.is_dir():
            cutoff = time.time() - TRASH_DAYS * 86400
            for path in trash.rglob("*.txt"):
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)

    @staticmethod
    def _free_path(directory: Path, stem: str) -> Path:
        path, n = directory / f"{stem}.txt", 2
        while path.exists():
            path, n = directory / f"{stem} ({n}).txt", n + 1
        return path

    def _path(self, entry_id: str) -> Path:
        """Turn an id like '2026-11/name.txt' into a path, refusing anything outside the library."""
        if not isinstance(entry_id, str) or not _ID.match(entry_id) or ".." in entry_id.split("/"):
            raise FileNotFoundError(entry_id)
        path = self.root / entry_id
        if path.resolve().parent.parent != self.root.resolve():
            raise FileNotFoundError(entry_id)
        return path

    # -- index

    def _load(self, path: Path, entry_id: str, mtime: int) -> Entry:
        meta, text = _parse(path.read_text(encoding="utf-8", errors="replace"))
        m = re.match(r"^(\d{4}-\d{2}-\d{2}) - (.*)$", path.stem)
        title = meta.get("title") or (m.group(2) if m else path.stem)
        transcribed = meta.get("transcribed") or (
            f"{m.group(1)} 00:00" if m else datetime.fromtimestamp(mtime / 1e9).strftime("%Y-%m-%d %H:%M"))
        link = meta.get("link")
        platform = meta.get("platform") or platform_of(link)
        channel = meta.get("channel")
        haystack = " ".join(filter(None, (title, channel, platform, link, text))).lower()
        return Entry(entry_id, title, link, url_key(link), transcribed, meta.get("language"),
                     meta.get("source"), platform, channel, text, mtime, haystack)

    def refresh(self) -> list[Entry]:
        """Re-scan the folder; only new or changed files are read. Returns entries, newest first."""
        with self._lock:
            found: dict[str, Entry] = {}
            if self.root.is_dir():
                for month in self.root.iterdir():
                    if not (month.is_dir() and _MONTH_DIR.match(month.name)):
                        continue
                    for path in month.glob("*.txt"):
                        entry_id = f"{month.name}/{path.name}"
                        try:
                            mtime = path.stat().st_mtime_ns
                            cached = self._index.get(entry_id)
                            found[entry_id] = (cached if cached and cached.mtime == mtime
                                               else self._load(path, entry_id, mtime))
                        except OSError:
                            continue
            self._index = found
            return sorted(found.values(), key=lambda e: (e.transcribed, e.id), reverse=True)

    def query(self, q: str = "", offset: int = 0, limit: int = 50) -> dict:
        """Newest-first page of transcripts; `q` matches all words in title, channel, link or text."""
        entries = self.refresh()
        total_all = len(entries)
        terms = q.lower().split()
        if terms:
            entries = [e for e in entries if all(t in e.haystack for t in terms)]
        items = []
        for e in entries[offset: offset + limit]:
            item = e.summary()
            if terms:
                item["snippet"] = _snippet(e.text, terms)
            items.append(item)
        return {"total": len(entries), "all": total_all, "items": items}

    def get(self, entry_id: str) -> dict:
        path = self._path(entry_id)
        if not path.is_file():
            raise FileNotFoundError(entry_id)
        return self._load(path, entry_id, path.stat().st_mtime_ns).full()

    def find_by_url(self, url: str) -> dict | None:
        key = url_key(url)
        if not key:
            return None
        return next((e.summary() for e in self.refresh() if e.key == key), None)

    # -- changes

    def save(self, t: Transcript, now: datetime | None = None) -> str:
        """Write '<YYYY-MM>/<YYYY-MM-DD> - <video name>.txt' and return its id."""
        now = now or datetime.now()
        name = video_name(t)
        month = self.root / f"{now:%Y-%m}"
        month.mkdir(parents=True, exist_ok=True)
        path = self._free_path(month, f"{now:%Y-%m-%d} - {_safe_filename(name)}")
        header = {
            "Title": name,
            "Link": t.url,
            "Platform": platform_of(t.url),
            "Channel": t.extra.get("channel"),
            "Transcribed": f"{now:%Y-%m-%d %H:%M}",
            "Language": t.language,
            "Source": "platform captions" if t.source == "captions"
            else f"speech recognition ({t.extra.get('model')})",
        }
        lines = [f"{k}: {_one_line(v)}" for k, v in header.items() if v]
        path.write_text("\n".join(lines) + _HEADER_END + t.text + "\n", encoding="utf-8")
        return f"{month.name}/{path.name}"

    def delete(self, entry_id: str) -> None:
        """Move to the trash (kept TRASH_DAYS days) so it can be restored."""
        path = self._path(entry_id)
        if not path.is_file():
            raise FileNotFoundError(entry_id)
        target_dir = self.root / _TRASH / path.parent.name
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / path.name
        target.unlink(missing_ok=True)
        shutil.move(str(path), target)
        os.utime(target)  # trash age counts from the delete

    def restore(self, entry_id: str) -> str:
        if not isinstance(entry_id, str) or not _ID.match(entry_id):
            raise FileNotFoundError(entry_id)
        month, name = entry_id.split("/")
        source = self.root / _TRASH / month / name
        if not source.is_file():
            raise FileNotFoundError(entry_id)
        (self.root / month).mkdir(parents=True, exist_ok=True)
        target = self._free_path(self.root / month, Path(name).stem)
        shutil.move(str(source), target)
        return f"{month}/{target.name}"


# --------------------------------------------------------------------------- OS helpers


def display_path(path: Path) -> str:
    """Show WSL paths the way Windows users know them (C:\\Users\\... or \\\\wsl.localhost\\...)."""
    if is_wsl():
        try:
            return subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True,
                                  timeout=5).stdout.strip() or str(path)
        except (OSError, subprocess.SubprocessError):
            pass
    return str(path)


def open_in_file_manager(path: Path) -> None:
    """Show a folder (or select a file) in Windows Explorer / the desktop file manager."""
    if is_wsl():
        win = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True).stdout.strip()
        args = ["explorer.exe", f"/select,{win}"] if path.is_file() else ["explorer.exe", win]
    else:
        args = ["xdg-open", str(path if path.is_dir() else path.parent)]
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
