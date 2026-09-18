"""The queue shared by every file-to-file tool.

The YouTube converter has its own richer job model because it goes through
four different steps.  Tools that turn one file into another file all share
this one, so the queue, the progress and the error handling are written once.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

_counter = itertools.count(1)


class FileStage(str, Enum):
    """Where one file currently is."""

    QUEUED = "Queued"
    WORKING = "Working"
    DONE = "Done"
    SKIPPED = "Skipped"
    FAILED = "Failed"
    CANCELLED = "Cancelled"

    @property
    def is_final(self) -> bool:
        return self in (FileStage.DONE, FileStage.SKIPPED, FileStage.FAILED, FileStage.CANCELLED)

    @property
    def is_success(self) -> bool:
        return self in (FileStage.DONE, FileStage.SKIPPED)


@dataclass
class FileJob:
    """One input file travelling through a tool."""

    source: Path
    destination: Path                       # folder the result is written into
    id: int = field(default_factory=lambda: next(_counter))
    stage: FileStage = FileStage.QUEUED
    progress: float = 0.0                   # 0..100
    message: str = ""
    error: str = ""
    output: Optional[Path] = None
    source_bytes: int = 0
    output_bytes: int = 0
    info: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.source = Path(self.source)
        self.destination = Path(self.destination)
        if not self.source_bytes:
            try:
                self.source_bytes = self.source.stat().st_size
            except OSError:
                self.source_bytes = 0

    # ------------------------------------------------------------- display
    @property
    def display_name(self) -> str:
        return self.source.name

    @property
    def saving_percent(self) -> float:
        if self.source_bytes <= 0 or self.output_bytes <= 0:
            return 0.0
        return (self.source_bytes - self.output_bytes) * 100.0 / self.source_bytes

    @property
    def detail(self) -> str:
        return self.error or self.message

    def reset(self) -> None:
        self.stage = FileStage.QUEUED
        self.progress = 0.0
        self.message = ""
        self.error = ""
        self.output = None
        self.output_bytes = 0
        self.info.clear()


def snapshot(job: FileJob) -> Dict:
    """A plain copy, safe to hand from a worker thread to the interface."""
    return {
        "id": job.id,
        "source": str(job.source),
        "name": job.display_name,
        "destination": str(job.destination),
        "stage": job.stage.value,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "output": str(job.output) if job.output else "",
        "source_bytes": job.source_bytes,
        "output_bytes": job.output_bytes,
        "info": dict(job.info),
    }


def apply_snapshot(job: FileJob, data: Dict) -> None:
    """Copy a snapshot back onto the job kept by the interface."""
    job.stage = FileStage(data["stage"])
    job.progress = float(data.get("progress", 0.0))
    job.message = data.get("message", "")
    job.error = data.get("error", "")
    job.output = Path(data["output"]) if data.get("output") else None
    job.source_bytes = int(data.get("source_bytes", job.source_bytes))
    job.output_bytes = int(data.get("output_bytes", 0))
    job.destination = Path(data.get("destination") or job.destination)
    job.info = dict(data.get("info") or {})
