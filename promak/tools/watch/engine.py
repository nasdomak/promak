"""A folder Promak keeps an eye on.

While the watch is on, every file that **arrives** in the folder - saved by a
scanner, a camera, a download, a colleague - goes through a tool or a
recipe, and the result lands in an output folder.

* the folder is looked at every few seconds (no extra component needed);
* a file is taken only once it has **stopped growing** (same size and date
  on two looks in a row), so a copy still in progress is never caught half way;
* files already there when the watch starts are left alone, unless asked;
* each file is done once; the originals are never changed;
* the output folder cannot be inside the watched one (the results would be
  taken again and again).

Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from promak.core.filejobs import FileJob
from promak.tools.recipes.engine import Recipe, RecipeBatch

log = logging.getLogger(__name__)

TEMPORARY_ENDINGS = (".part", ".crdownload", ".tmp", ".download", ".partial", "~")


@dataclass
class WatchOptions:
    folder: Optional[Path] = None
    output: Optional[Path] = None
    recursive: bool = False
    include_existing: bool = False

    def validate(self) -> Optional[str]:
        if not self.folder or not Path(self.folder).is_dir():
            return "Choose the folder to watch."
        if not self.output:
            return "Choose the folder for the results."
        folder, output = Path(self.folder).resolve(), Path(self.output).resolve()
        if folder == output:
            return "The results cannot go into the watched folder itself: choose another folder."
        if self.recursive and folder in output.parents:
            return "The results cannot go inside the watched folder when its sub-folders are watched too."
        return None


class FolderWatcher:
    """Says which files are new and finished, each time it is asked."""

    def __init__(self, options: WatchOptions, extensions: Sequence[str] = ()) -> None:
        problem = options.validate()
        if problem:
            raise ValueError(problem)
        self.options = options
        self.extensions = tuple(e.lower() for e in extensions)
        self._last: Dict[str, Tuple[int, float]] = {}
        self._done: Dict[str, Tuple[int, float]] = {}
        self._output = Path(options.output).resolve()
        if not options.include_existing:
            for path, stamp in self._scan().items():
                self._done[path] = stamp
                self._last[path] = stamp

    def _scan(self) -> Dict[str, Tuple[int, float]]:
        found: Dict[str, Tuple[int, float]] = {}
        root = Path(self.options.folder)
        for folder, dirs, files in os.walk(root):
            if not self.options.recursive:
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith(".") and (Path(folder) / d).resolve() != self._output]
            for name in files:
                lowered = name.lower()
                if name.startswith((".", "~$")) or lowered.endswith(TEMPORARY_ENDINGS):
                    continue
                if self.extensions and os.path.splitext(lowered)[1] not in self.extensions:
                    continue
                path = os.path.join(folder, name)
                try:
                    stat = os.stat(path)
                except OSError:
                    continue
                found[path] = (stat.st_size, stat.st_mtime)
        return found

    def poll(self) -> List[Path]:
        """The files that arrived and have stopped changing since the last look."""
        now = self._scan()
        ready: List[Path] = []
        for path, stamp in now.items():
            previous = self._last.get(path)
            self._last[path] = stamp
            if path in self._done:
                if self._done[path] == stamp:
                    continue
                del self._done[path]       # the same name came back with new content: do it again
            if previous == stamp and stamp[0] > 0 and _can_open(path):
                ready.append(Path(path))
                self._done[path] = stamp
        for gone in set(self._last) - set(now):
            self._last.pop(gone, None)
            self._done.pop(gone, None)
        return sorted(ready)


def _can_open(path: str) -> bool:
    """False while another program still has the file open for writing (Windows)."""
    try:
        with open(path, "rb"):
            pass
        return True
    except OSError:
        return False


def process(path: Path, recipe: Recipe, output: Path, on_log=None, cancel_event=None) -> FileJob:
    """Put one arrived file through the recipe; returns its job (done or failed)."""
    job = FileJob(source=path, destination=output)
    RecipeBatch(recipe, on_log=on_log, cancel_event=cancel_event).run([job])
    return job


def watch_forever(options: WatchOptions, recipe: Recipe, interval: float = 3.0, on_log=None,
                  stop=lambda: False) -> int:
    """The command-line watch: runs until ``stop()`` is true or Ctrl+C."""
    say = on_log or (lambda level, text: None)
    watcher = FolderWatcher(options, recipe.accepted_extensions())
    count = 0
    say("info", f"Watching {options.folder} - every new file goes through '{recipe.name}' into {options.output}.")
    try:
        while not stop():
            for path in watcher.poll():
                job = process(path, recipe, Path(options.output), on_log=say)
                count += 1
                if job.error:
                    say("error", f"{path.name}: {job.error}")
                else:
                    say("info", f"{path.name} -> {job.output.name if job.output else job.message}")
            time.sleep(interval)
    except KeyboardInterrupt:
        pass
    return count
