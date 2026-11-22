"""Paste a link to a short video and get a transcript."""

from .core import MAX_DURATION_SECONDS, TranscriptionError, transcribe
from .models import Segment, Transcript

__all__ = ["MAX_DURATION_SECONDS", "Segment", "Transcript", "TranscriptionError", "transcribe"]
__version__ = "0.1.0"
