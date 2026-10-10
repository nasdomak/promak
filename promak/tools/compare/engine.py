"""Comparing two folders, and copying across what one of them is missing.

Every file is matched by its path inside the two folders and gets one of
four answers:

* **only on the left** / **only on the right**;
* **identical** - same size and the same content (a fingerprint of both
  files is compared), or with *quick* comparison same size and same date;
* **different** - same name, other content.

The files missing on one side can then be copied across - left to right,
right to left, or both - after a preview; nothing is ever overwritten or
deleted, and the last copy can be undone.  Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from promak.core.batch import BatchCancelled
from promak.core.fileops import COPY, FileOpError, Journal, file_hash, save_journal, transfer
from promak.core.imaging import human_size

log = logging.getLogger(__name__)

TOOL = "compare"

ONLY_LEFT = "only on the left"
ONLY_RIGHT = "only on the right"
IDENTICAL = "identical"
DIFFERENT = "different"

LEFT_TO_RIGHT = "left-to-right"
RIGHT_TO_LEFT = "right-to-left"
BOTH_WAYS = "both"
DIRECTIONS = [
    ("Copy what the right folder is missing (left to right)", LEFT_TO_RIGHT),
    ("Copy what the left folder is missing (right to left)", RIGHT_TO_LEFT),
    ("Both ways: in the end both have every file", BOTH_WAYS),
]

Progress = Callable[[float, str], None]


@dataclass
class CompareOptions:
    left: Optional[Path] = None
    right: Optional[Path] = None
    recursive: bool = True
    quick: bool = False             # size and date instead of the content
    include_hidden: bool = False

    def validate(self) -> Optional[str]:
        for name, folder in (("left", self.left), ("right", self.right)):
            if not folder:
                return f"Choose the {name} folder."
            if not Path(folder).is_dir():
                return f"The {name} folder does not exist: {folder}"
        if Path(self.left).resolve() == Path(self.right).resolve():
            return "Choose two different folders."
        left, right = Path(self.left).resolve(), Path(self.right).resolve()
        if self.recursive and (left in right.parents or right in left.parents):
            return "One folder is inside the other: choose two separate folders, or untick the sub-folders."
        return None


@dataclass
class Side:
    size: int
    modified: float

    @property
    def text(self) -> str:
        return f"{human_size(self.size)}, {datetime.fromtimestamp(self.modified).strftime('%Y-%m-%d %H:%M')}"


@dataclass
class Difference:
    relative: str                   # path inside the folders, with "/"
    status: str
    left: Optional[Side] = None
    right: Optional[Side] = None

    @property
    def newer(self) -> str:
        if self.left and self.right and self.status == DIFFERENT:
            if abs(self.left.modified - self.right.modified) < 2:
                return ""
            return "left is newer" if self.left.modified > self.right.modified else "right is newer"
        return ""


def _listing(root: Path, recursive: bool, include_hidden: bool, cancel: threading.Event) -> Dict[str, Side]:
    found: Dict[str, Side] = {}
    for folder, dirs, files in os.walk(root):
        if cancel.is_set():
            raise BatchCancelled()
        if not include_hidden:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
        if not recursive:
            dirs[:] = []
        for name in files:
            if not include_hidden and name.startswith("."):
                continue
            path = Path(folder) / name
            try:
                stat = path.stat()
            except OSError:
                continue
            key = path.relative_to(root).as_posix()
            found[key] = Side(stat.st_size, stat.st_mtime)
    return found


def compare_folders(options: CompareOptions, progress: Progress = lambda *_: None,
                    cancel_event: Optional[threading.Event] = None) -> List[Difference]:
    problem = options.validate()
    if problem:
        raise FileOpError(problem)
    cancel = cancel_event or threading.Event()
    left_root, right_root = Path(options.left), Path(options.right)
    progress(0.0, "listing the files")
    left = _listing(left_root, options.recursive, options.include_hidden, cancel)
    right = _listing(right_root, options.recursive, options.include_hidden, cancel)
    # Windows does not tell "Photo.JPG" from "photo.jpg": neither does the comparison
    right_by_key = {key.casefold(): key for key in right}
    results: List[Difference] = []
    matched_right = set()
    both = [key for key in left if key.casefold() in right_by_key]
    total_bytes = sum(left[key].size for key in both) or 1
    done_bytes = 0
    for key in sorted(left, key=str.casefold):
        other = right_by_key.get(key.casefold())
        if other is None:
            results.append(Difference(key, ONLY_LEFT, left=left[key]))
            continue
        matched_right.add(other)
        a, b = left[key], right[other]
        if a.size != b.size:
            status = DIFFERENT
        elif options.quick:
            status = IDENTICAL if abs(a.modified - b.modified) < 2 else DIFFERENT
        else:
            try:
                same = file_hash(left_root / key, cancel_event=cancel) == file_hash(right_root / other, cancel_event=cancel)
            except OSError:
                same = False
            status = IDENTICAL if same else DIFFERENT
        done_bytes += a.size
        progress(done_bytes / total_bytes, key)
        results.append(Difference(key, status, left=a, right=b))
    for key in sorted(right, key=str.casefold):
        if key not in matched_right:
            results.append(Difference(key, ONLY_RIGHT, right=right[key]))
    results.sort(key=lambda d: d.relative.casefold())
    return results


def counts(results: List[Difference]) -> Dict[str, int]:
    out = {ONLY_LEFT: 0, ONLY_RIGHT: 0, DIFFERENT: 0, IDENTICAL: 0}
    for item in results:
        out[item.status] += 1
    return out


def summary_text(results: List[Difference]) -> str:
    c = counts(results)
    return (f"{c[ONLY_LEFT]} only on the left, {c[ONLY_RIGHT]} only on the right, "
            f"{c[DIFFERENT]} different, {c[IDENTICAL]} identical.")


def copy_plan(results: List[Difference], direction: str) -> List[Difference]:
    wanted = {LEFT_TO_RIGHT: {ONLY_LEFT}, RIGHT_TO_LEFT: {ONLY_RIGHT}, BOTH_WAYS: {ONLY_LEFT, ONLY_RIGHT}}[direction]
    return [item for item in results if item.status in wanted]


def copy_missing(results: List[Difference], options: CompareOptions, direction: str,
                 progress: Progress = lambda *_: None, cancel_event: Optional[threading.Event] = None,
                 on_log: Callable[[str, str], None] = lambda *_: None,
                 journal_dir: Optional[Path] = None) -> Dict[str, int]:
    """Copy the missing files across; never overwrites, keeps the dates."""
    cancel = cancel_event or threading.Event()
    plan = copy_plan(results, direction)
    left_root, right_root = Path(options.left), Path(options.right)
    journal = Journal(tool=TOOL)
    result = {"done": 0, "failed": 0, "bytes": 0}
    try:
        for index, item in enumerate(plan, start=1):
            if cancel.is_set():
                break
            source_root, target_root = (left_root, right_root) if item.status == ONLY_LEFT else (right_root, left_root)
            source, target = source_root / item.relative, target_root / item.relative
            try:
                if target.exists():
                    raise FileOpError(f"{item.relative} appeared on the other side meanwhile: left alone.")
                landed = transfer(source, target, COPY)
                journal.add(COPY, source, landed)
                result["done"] += 1
                result["bytes"] += source.stat().st_size
            except (FileOpError, OSError) as exc:
                result["failed"] += 1
                on_log("error", str(exc))
            progress(index / max(1, len(plan)), item.relative)
    finally:
        if journal.entries:
            save_journal(journal, journal_dir)
    return result
