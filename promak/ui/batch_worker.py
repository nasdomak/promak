"""Qt thread wrapper around :class:`promak.core.batch.BatchEngine`.

The engine is plain Python; this class only moves its callbacks onto Qt
signals so the window never freezes while files are being processed.
"""

from __future__ import annotations

import threading
from typing import Callable, Dict, List

from PySide6.QtCore import QThread, Signal

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, snapshot

EngineFactory = Callable[[threading.Event], BatchEngine]


class BatchWorker(QThread):
    """Runs a file queue in the background."""

    job_updated = Signal(dict)
    log_message = Signal(str, str)
    run_finished = Signal(dict)

    def __init__(self, jobs: List[FileJob], engine_factory: EngineFactory, parent=None) -> None:
        super().__init__(parent)
        self._jobs = jobs
        self._engine_factory = engine_factory
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            engine = self._engine_factory(self.cancel_event)
            engine.on_update = lambda job: self.job_updated.emit(snapshot(job))
            engine.on_log = lambda level, message: self.log_message.emit(level, message)
            summary: Dict[str, int] = engine.run(self._jobs)
        except Exception as exc:  # pragma: no cover - safety net
            self.log_message.emit("error", f"Unexpected error: {exc}")
            summary = {"done": 0, "failed": len(self._jobs), "cancelled": 0, "skipped": 0}
        self.run_finished.emit(summary)
