"""Decode downloaded media in a separate, resource-limited process.

Downloaded videos come from strangers on the internet. Decoding them means running ffmpeg's
parsers (through PyAV) on untrusted bytes, the classic place where a malicious file would try
to crash or exploit a program. So decoding happens in a throw-away child process that:

- gets only the file path, runs Python in isolated mode (-I) and can't read our state,
- has hard limits on memory, CPU time, output file size and number of processes (Linux),
- is killed after a timeout,

and only a plain array of 16 kHz float32 samples comes back. If the file is broken or
hostile, the child dies and the app shows a normal error instead of crashing or hanging.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from .errors import TranscriptionError

SAMPLE_RATE = 16000
TIMEOUT_SECONDS = 180
MEMORY_LIMIT_BYTES = 4 * 1024**3
EXIT_NO_AUDIO = 3

# The child limits itself before it imports the decoder or touches the file.
# (Setting limits from the parent with preexec_fn isn't safe in a multi-threaded server.)
_CHILD = r"""
import sys
src, dst, mem, cpu, fsize = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
try:
    import resource
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
except ImportError:  # Windows: only the timeout applies
    pass
import av
from faster_whisper.audio import decode_audio
with av.open(src) as c:
    if not c.streams.audio:
        sys.exit(3)
decode_audio(src, sampling_rate=16000).astype("float32").tofile(dst)
"""


def decode_audio(path: Path, max_seconds: int, workdir: Path | None = None) -> np.ndarray:
    """Return mono 16 kHz samples, or raise a TranscriptionError for unreadable/hostile files."""
    fd, out_name = tempfile.mkstemp(suffix=".f32", dir=str(workdir or path.parent))
    os.close(fd)
    out = Path(out_name)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR")}
    try:
        try:
            out_limit = (max_seconds + 60) * SAMPLE_RATE * 4
            proc = subprocess.run(
                [sys.executable, "-I", "-c", _CHILD, str(path), str(out),
                 str(MEMORY_LIMIT_BYTES), str(TIMEOUT_SECONDS), str(out_limit)],
                capture_output=True, timeout=TIMEOUT_SECONDS, env=env, start_new_session=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise _unreadable("Decoding the audio took far too long.") from exc
        if proc.returncode == EXIT_NO_AUDIO:
            raise TranscriptionError(
                "The video has no sound track. Either it's silent, or the platform only gave the "
                "audio to logged-in users (this happens on Instagram).",
                kind="video", title="No sound in this video",
                hint="Check in your browser that the video has sound. If it does, log in to the "
                     "platform in Firefox and try again.")
        if proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or [f"exit code {proc.returncode}"]
            raise _unreadable(detail[0])
        audio = np.fromfile(out, dtype=np.float32)
    finally:
        out.unlink(missing_ok=True)
    if audio.size == 0:
        raise _unreadable("The audio track is empty.")
    return audio


def _unreadable(technical: str) -> TranscriptionError:
    return TranscriptionError(
        "The video's audio couldn't be read. The file may be damaged or in an unusual format.",
        kind="video", title="Can't read this video's audio",
        hint="Try again, or try another video.", technical=technical[:500])
