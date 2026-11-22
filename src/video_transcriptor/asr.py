"""Local speech-to-text with faster-whisper."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from .models import Segment

log = logging.getLogger(__name__)

MODELS = (
    "small.en",          # English only, fast
    "distil-large-v3",   # English only, near large-v3 quality at a fraction of the cost
    "tiny",
    "base",
    "small",
    "medium",
    "large-v3-turbo",    # best multilingual speed/quality balance
    "large-v3",
)
ENGLISH_ONLY_MODELS = ("small.en", "distil-large-v3")
DEFAULT_MODEL = "small.en"
DEFAULT_MULTILINGUAL_MODEL = "large-v3-turbo"

_lock = threading.Lock()
_cache: dict[tuple[str, str], object] = {}


def _preload_cuda_libs() -> None:
    """Load CUDA libraries installed via pip (the `gpu` extra) so CTranslate2 can find them."""
    import ctypes
    import importlib.util

    libs: list[Path] = []
    for pkg in ("nvidia.cublas", "nvidia.cudnn"):
        try:
            spec = importlib.util.find_spec(pkg)
        except ModuleNotFoundError:
            continue
        for location in (spec.submodule_search_locations or []) if spec else []:
            libs += sorted((Path(location) / "lib").glob("lib*.so*"))
    # Libraries depend on each other; keep retrying until no more progress is made.
    pending = libs
    while pending:
        failed = []
        for lib in pending:
            try:
                ctypes.CDLL(str(lib), mode=ctypes.RTLD_GLOBAL)
            except OSError:
                failed.append(lib)
        if len(failed) == len(pending):
            break
        pending = failed


def _cuda_available() -> bool:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() == 0:
            return False
    except Exception:
        return False
    _preload_cuda_libs()
    return True


def _get_model(name: str, device: str):
    from faster_whisper import WhisperModel

    key = (name, device)
    if key not in _cache:
        compute_type = "float16" if device == "cuda" else "int8"
        log.info("Loading model %s on %s (%s)", name, device, compute_type)
        _cache[key] = WhisperModel(name, device=device, compute_type=compute_type)
    return _cache[key]


def transcribe_file(
    path,
    model: str = DEFAULT_MODEL,
    language: str | None = None,
    device: str = "auto",
) -> tuple[list[Segment], str | None, float]:
    """Transcribe a file path or an array of 16 kHz mono samples.

    Returns (segments, detected language, duration in seconds).
    """
    if model not in MODELS:
        raise ValueError(f"Unknown model {model!r}; choose from {', '.join(MODELS)}")
    if model in ENGLISH_ONLY_MODELS:
        language = "en"
    if device == "auto":
        devices = ["cuda", "cpu"] if _cuda_available() else ["cpu"]
    else:
        devices = [device]

    for i, dev in enumerate(devices):
        try:
            # One transcription at a time: models are large and share the CPU/GPU.
            with _lock:
                whisper = _get_model(model, dev)
                segments, info = whisper.transcribe(
                    path if hasattr(path, "dtype") else str(path),
                    language=language, vad_filter=True, beam_size=5
                )
                result = [Segment(s.start, s.end, s.text.strip()) for s in segments]
            return result, info.language, info.duration
        except RuntimeError as exc:
            # Typically missing CUDA/cuDNN libraries: fall back to CPU.
            if i == len(devices) - 1:
                raise
            log.warning("Transcription on %s failed (%s); falling back to %s", dev, exc, devices[i + 1])
            _cache.pop((model, dev), None)
    raise AssertionError("unreachable")
