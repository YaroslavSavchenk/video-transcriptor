"""Background transcription jobs with progress and cancelling.

The page starts a job, polls its progress (stage text + fraction) and can cancel it. Only one
job runs at a time: models are large and share the CPU/GPU, and the app is single-user.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from .core import Control
from .errors import Cancelled, TranscriptionError

log = logging.getLogger(__name__)
KEEP_FINISHED_SECONDS = 600


@dataclass
class Job:
    id: str
    status: str = "running"  # running | done | error | cancelled
    stage: str = "Starting…"
    progress: float | None = None
    result: dict | None = None
    error: dict | None = None
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    control: Control = field(default_factory=Control)
    thread: threading.Thread | None = None

    def view(self) -> dict:
        return {"id": self.id, "status": self.status, "stage": self.stage, "progress": self.progress,
                "elapsed": round((self.finished or time.monotonic()) - self.started, 1),
                "result": self.result, "error": self.error}


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def running(self) -> Job | None:
        return next((j for j in self._jobs.values() if j.status == "running"), None)

    def start(self, work: Callable[[Control], dict]) -> Job:
        with self._lock:
            self._prune()
            if self.running():
                raise TranscriptionError(
                    "Another video is still being transcribed.", kind="settings",
                    title="Already busy", hint="Wait for it to finish, or cancel it first.")
            job = Job(id=uuid.uuid4().hex)

            def progress(stage: str, fraction: float | None) -> None:
                job.stage, job.progress = stage, fraction

            job.control.on_progress = progress
            self._jobs[job.id] = job

        def run() -> None:
            try:
                job.result = work(job.control)
                job.status = "done"
            except Cancelled:
                job.status = "cancelled"
            except TranscriptionError as exc:
                job.error, job.status = exc.to_dict(), "error"
            except Exception as exc:  # never let a job die silently
                log.exception("Transcription job failed")
                job.error = TranscriptionError(
                    "An unexpected error happened inside the app.", kind="app",
                    title="Something went wrong in the app",
                    hint="Try again. If it keeps happening, restart the app or update it.",
                    technical=f"{type(exc).__name__}: {exc}").to_dict()
                job.status = "error"
            finally:
                job.finished = time.monotonic()

        job.thread = threading.Thread(target=run, name=f"job-{job.id[:8]}", daemon=True)
        job.thread.start()
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> Job | None:
        job = self._jobs.get(job_id)
        if job and job.status == "running":
            job.stage = "Cancelling…"
            job.control.cancel_event.set()
        return job

    def shutdown(self, timeout: float = 10) -> None:
        """Cancel running jobs and give them a moment to clean up their temp files."""
        for job in list(self._jobs.values()):
            if job.status == "running":
                job.control.cancel_event.set()
        deadline = time.monotonic() + timeout
        for job in list(self._jobs.values()):
            if job.thread and job.thread.is_alive():
                job.thread.join(max(0.0, deadline - time.monotonic()))

    def _prune(self) -> None:
        now = time.monotonic()
        for job_id, job in list(self._jobs.items()):
            if job.finished and now - job.finished > KEEP_FINISHED_SECONDS:
                del self._jobs[job_id]
