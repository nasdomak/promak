"""Qt thread wrapper around the conversion pipeline.

The pipeline itself is pure Python; this class only moves its callbacks
onto Qt signals so the interface never freezes.
"""

from __future__ import annotations

import threading
from typing import Dict, List

from PySide6.QtCore import QThread, Signal

from promak.tools.video.models import Job, JobOptions
from promak.tools.video.pipeline import PipelineEngine


def snapshot(job: Job) -> Dict:
    """A plain copy of a job, safe to hand over to the GUI thread."""
    return {
        "id": job.id,
        "url": job.url,
        "title": job.title,
        "destination": str(job.destination),
        "stage": job.stage.value,
        "progress": job.progress,
        "overall": job.overall,
        "message": job.message,
        "error": job.error,
        "outputs": {key: str(path) for key, path in job.outputs.items()},
    }


class PipelineWorker(QThread):
    """Runs the queue in the background."""

    job_updated = Signal(dict)
    log_message = Signal(str, str)
    run_finished = Signal(dict)

    def __init__(self, jobs: List[Job], options: JobOptions, parent=None) -> None:
        super().__init__(parent)
        self._jobs = jobs
        self._options = options
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:  # noqa: D102 - QThread entry point
        engine = PipelineEngine(
            self._options,
            on_update=lambda job: self.job_updated.emit(snapshot(job)),
            on_log=lambda level, message: self.log_message.emit(level, message),
            cancel_event=self.cancel_event,
        )
        try:
            summary = engine.run(self._jobs)
        except Exception as exc:  # pragma: no cover - safety net
            self.log_message.emit("error", f"Unexpected error: {exc}")
            summary = {"done": 0, "failed": len(self._jobs), "cancelled": 0}
        self.run_finished.emit(summary)
