"""Sequential batch runner shared by the file tools.

It owns everything that is the same in every tool - going through the queue
one file at a time, reporting progress, isolating a failure so the rest of
the queue keeps going, and stopping when the user asks.  A tool only has to
say what to do with one file.

Zero Qt imports, so a test can drive it directly.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import ImageToolError, ensure_writable_dir

log = logging.getLogger(__name__)

UpdateCallback = Callable[[FileJob], None]
LogCallback = Callable[[str, str], None]        # (level, message)
ProgressCallback = Callable[..., None]          # (percent, detail="")


class BatchCancelled(Exception):
    """The user pressed Stop."""


class BatchEngine:
    """Runs a queue of :class:`FileJob` one after the other.

    Subclasses implement :meth:`process_one`.  Everything else is free.
    """

    #: shown in the log line that opens a run
    what: str = "file(s)"

    def __init__(
        self,
        *,
        on_update: Optional[UpdateCallback] = None,
        on_log: Optional[LogCallback] = None,
        cancel_event: Optional[threading.Event] = None,
    ) -> None:
        self.on_update = on_update or (lambda job: None)
        self.on_log = on_log or (lambda level, message: None)
        self.cancel_event = cancel_event or threading.Event()

    # ------------------------------------------------------------- helpers
    def _log(self, level: str, message: str) -> None:
        self.on_log(level, message)
        getattr(log, level if level in ("debug", "info", "warning", "error") else "info")(message)

    def check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise BatchCancelled()

    def _reporter(self, job: FileJob) -> ProgressCallback:
        def report(percent: float, detail: str = "") -> None:
            job.progress = max(0.0, min(100.0, float(percent)))
            if detail:
                job.message = detail
            self.on_update(job)

        return report

    # ---------------------------------------------------------------- main
    def run(self, jobs: List[FileJob]) -> Dict[str, int]:
        summary = {"done": 0, "failed": 0, "cancelled": 0, "skipped": 0}
        started = time.time()
        pending = [job for job in jobs if not job.stage.is_final]
        self._log("info", f"Starting {len(pending)} {self.what}.")

        for index, job in enumerate(pending, start=1):
            if self.cancel_event.is_set():
                job.stage = FileStage.CANCELLED
                job.message = "Cancelled before starting"
                summary["cancelled"] += 1
                self.on_update(job)
                continue

            self._log("info", f"[{index}/{len(pending)}] {job.display_name}")
            job.stage = FileStage.WORKING
            job.progress = 0.0
            job.message = "starting"
            job.error = ""
            self.on_update(job)

            try:
                self.prepare(job)
                self.process_one(job, self._reporter(job))
                if job.stage is FileStage.SKIPPED:
                    summary["skipped"] += 1
                    self._log("info", f"Left as it was: {job.display_name} - {job.message}")
                else:
                    job.stage = FileStage.DONE
                    job.progress = 100.0
                    job.message = job.message or "Completed"
                    summary["done"] += 1
                    self._log("info", f"Finished: {job.display_name} -> {self.describe_result(job)}")
            except BatchCancelled:
                job.stage = FileStage.CANCELLED
                job.message = "Cancelled"
                summary["cancelled"] += 1
                self._log("warning", f"Cancelled: {job.display_name}")
            except ImageToolError as exc:
                job.stage = FileStage.FAILED
                job.error = str(exc)
                summary["failed"] += 1
                self._log("error", f"Failed: {job.display_name} - {exc}")
            except MemoryError:
                job.stage = FileStage.FAILED
                job.error = (
                    "The computer ran out of memory on this picture. "
                    "Try one file at a time, or a smaller picture."
                )
                summary["failed"] += 1
                self._log("error", f"Failed: {job.display_name} - out of memory")
            except OSError as exc:
                job.stage = FileStage.FAILED
                job.error = self.explain_os_error(exc, job)
                summary["failed"] += 1
                self._log("error", f"Failed: {job.display_name} - {job.error}")
            except Exception as exc:  # last resort, never kill the queue
                job.stage = FileStage.FAILED
                job.error = f"Unexpected problem: {exc}"
                summary["failed"] += 1
                self._log("error", f"Failed: {job.display_name} - {exc}")
                log.debug("Job failure detail", exc_info=True)
            finally:
                self.on_update(job)

        elapsed = int(time.time() - started)
        self._log(
            "info",
            f"Run finished in {elapsed // 60}m {elapsed % 60}s - "
            f"{summary['done']} done, {summary['skipped']} left as they were, "
            f"{summary['failed']} failed, {summary['cancelled']} cancelled.",
        )
        return summary

    # --------------------------------------------------------- overridable
    def prepare(self, job: FileJob) -> None:
        """Checks done before every file. Extend, do not replace."""
        if not job.source.exists():
            raise ImageToolError(f"The file no longer exists: {job.source}")
        job.destination = ensure_writable_dir(job.destination)
        try:
            job.source_bytes = job.source.stat().st_size
        except OSError:  # pragma: no cover
            pass

    def process_one(self, job: FileJob, report: ProgressCallback) -> None:
        """Do the actual work on one file."""
        raise NotImplementedError

    def describe_result(self, job: FileJob) -> str:
        return job.output.name if job.output else job.message or "done"

    @staticmethod
    def explain_os_error(exc: OSError, job: FileJob) -> str:
        """Turn a system error into something a human can act on."""
        import errno

        code = getattr(exc, "errno", None)
        target = Path(getattr(exc, "filename", "") or job.destination)
        if code == errno.EACCES:
            return (
                f"Windows refused access to '{target}'. The file may be open in "
                "another program, or the folder may be read-only."
            )
        if code == errno.ENOSPC:
            return f"There is no free space left on the disk holding '{target}'."
        if code == errno.ENAMETOOLONG or (code == errno.EINVAL and len(str(target)) > 240):
            return (
                "The full path of the new file is too long for Windows. "
                "Choose a destination folder with a shorter name."
            )
        if code == errno.ENOENT:
            return f"This path does not exist any more: {target}"
        return f"The file could not be written: {exc}"
