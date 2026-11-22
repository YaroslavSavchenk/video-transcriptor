"""Save every transcript as a text file named after the date and the video."""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from .models import Transcript

_GENERIC_TITLE = re.compile(r"^(video|reel|post) by \S+$", re.IGNORECASE)
_HEADER_END = "\n---\n\n"


def is_wsl() -> bool:
    return "microsoft" in os.uname().release.lower() if hasattr(os, "uname") else False


@lru_cache(maxsize=1)
def _windows_documents() -> Path | None:
    """The Windows 'Documents' folder as a WSL path, so files are easy to find in Explorer."""
    try:
        out = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", "[Environment]::GetFolderPath('MyDocuments')"],
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
        if out:
            path = Path(subprocess.run(["wslpath", "-u", out], capture_output=True, text=True,
                                       timeout=5).stdout.strip())
            if path.is_dir():
                return path
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def default_dir() -> Path:
    docs = _windows_documents() if is_wsl() else None
    return (docs or Path.home() / "Documents") / "Transcripts"


def video_name(t: Transcript) -> str:
    """A human name for the video. Instagram titles are just 'Video by <user>', so use the caption."""
    title = (t.title or "").strip()
    channel = t.extra.get("channel")
    if not title or _GENERIC_TITLE.match(title):
        caption = " ".join((t.extra.get("description") or "").split())
        caption = re.split(r"(?<=[.!?])\s|#", caption)[0].strip() if caption else ""
        title = f"{channel} - {caption}" if channel and caption else (caption or title or "transcript")
    return title


def _safe_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", name)  # characters Windows doesn't allow
    name = re.sub(r"\s+", " ", name).strip(" .")
    if len(name) > max_len:
        cut = name[:max_len]
        name = (cut.rsplit(" ", 1)[0] if " " in cut[max_len // 2:] else cut) + "…"
    return name.rstrip(" .") or "transcript"


def save(t: Transcript, directory: Path, now: datetime | None = None) -> Path:
    """Write the transcript to '<YYYY-MM-DD> - <video name>.txt' and return the path."""
    now = now or datetime.now()
    directory.mkdir(parents=True, exist_ok=True)
    name = video_name(t)
    base = f"{now:%Y-%m-%d} - {_safe_filename(name)}"
    path = directory / f"{base}.txt"
    n = 2
    while path.exists():
        path = directory / f"{base} ({n}).txt"
        n += 1

    header = [f"Title: {name}"]
    if t.url:
        header.append(f"Link: {t.url}")
    header.append(f"Transcribed: {now:%Y-%m-%d %H:%M}")
    if t.language:
        header.append(f"Language: {t.language}")
    source = "platform captions" if t.source == "captions" else f"speech recognition ({t.extra.get('model')})"
    header.append(f"Source: {source}")
    path.write_text("\n".join(header) + _HEADER_END + t.text + "\n", encoding="utf-8")
    return path


def list_saved(directory: Path, limit: int = 200) -> list[dict]:
    if not directory.is_dir():
        return []
    files = sorted(directory.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    return [{"file": p.name, "name": p.stem} for p in files]


def read_saved(directory: Path, filename: str) -> dict:
    """Read one saved transcript. Only plain file names inside `directory` are allowed."""
    if Path(filename).name != filename or not filename.endswith(".txt"):
        raise FileNotFoundError(filename)
    path = directory / filename
    raw = path.read_text(encoding="utf-8")
    header, sep, text = raw.partition(_HEADER_END)
    meta = {}
    if sep:
        for line in header.splitlines():
            key, _, value = line.partition(": ")
            meta[key.lower()] = value
    else:
        text = raw
    return {"file": filename, "meta": meta, "text": text.strip()}


def display_path(path: Path) -> str:
    """Show WSL paths the way Windows users know them (C:\\Users\\...)."""
    if is_wsl() and str(path).startswith("/mnt/"):
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
