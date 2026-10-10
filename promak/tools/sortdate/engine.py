"""Sorting photos and videos into folders by the date they were taken.

    IMG_2031.JPG   ->   2026/07 - July/IMG_2031.JPG
    VID_0042.MP4   ->   2026/08 - August/VID_0042.MP4

For each file the best date available is used, in this order:

1. the camera's **date taken** (EXIF) for photos;
2. the **recording date** written inside a video (FFmpeg metadata);
3. the **file's own date** (last changed), when allowed - or the file goes
   to a "No date" folder instead.

The folders are made from a code, ``{year}/{month} - {monthname}`` by
default: a ``/`` makes a sub-folder.  Files are moved or copied, never
overwritten (a name already taken gets `` (2)``), a file identical to one
already in place is left alone, and the last run can be undone.  Nothing
here imports Qt.
"""

from __future__ import annotations

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

from promak.core.batch import BatchCancelled
from promak.core.fileops import COPY, MOVE, FileOpError, Journal, same_content, save_journal, transfer, walk_files
from promak.core.imaging import RASTER_EXTENSIONS, photo_facts
from promak.core.media import VIDEO_EXTENSIONS, creation_time
from promak.core.paths import safe_filename

log = logging.getLogger(__name__)

TOOL = "sortdate"

PHOTO_EXTENSIONS = RASTER_EXTENSIONS + (".heic", ".heif", ".dng", ".cr2", ".nef", ".arw")
MEDIA_EXTENSIONS = PHOTO_EXTENSIONS + VIDEO_EXTENSIONS

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

DEFAULT_PATTERN = "{year}/{month} - {monthname}"
PATTERN_EXAMPLES = [
    DEFAULT_PATTERN,
    "{year}/{year}-{month}",
    "{year}/{month} - {monthname}/{day}",
    "{year}-{month}-{day}",
    "{kind}/{year}",
]
PATTERN_PIECES = [
    ("{year}", "2026"),
    ("{month}", "07 (two digits)"),
    ("{monthname}", "July; {mon} for Jul"),
    ("{day}", "12"),
    ("{weekday}", "Sunday"),
    ("{date}", "2026-07-12"),
    ("{kind}", "Photos or Videos"),
    ("{ext}", "jpg, mp4..."),
    ("/", "starts a sub-folder"),
]
_PIECE = re.compile(r"\{(\w+)\}")
_KNOWN = {"year", "month", "monthname", "mon", "day", "weekday", "date", "kind", "ext"}

SOURCE_TAKEN = "date taken"
SOURCE_VIDEO = "recording date"
SOURCE_FILE = "file date"
SOURCE_NONE = "no date"

NO_DATE_FOLDER = "No date"

Progress = Callable[[float, str], None]


@dataclass
class SortOptions:
    folders: List[Path] = field(default_factory=list)
    recursive: bool = True
    target: Optional[Path] = None
    action: str = MOVE                  # or COPY
    pattern: str = DEFAULT_PATTERN
    all_files: bool = False             # False = photos and videos only
    use_file_date: bool = True          # False = files without a real date go to "No date"

    def validate(self) -> Optional[str]:
        if not self.folders:
            return "Add the folder that holds the photos and videos."
        for folder in self.folders:
            if not Path(folder).is_dir():
                return f"This folder does not exist: {folder}"
        if not self.target:
            return "Choose the folder where the dated folders are made."
        return check_pattern(self.pattern)


def check_pattern(pattern: str) -> Optional[str]:
    if not pattern.strip():
        return "Write how the folders are named, for example  {year}/{month} - {monthname}"
    unknown = sorted({m.group(1) for m in _PIECE.finditer(pattern)} - _KNOWN)
    if unknown:
        return "Unknown piece: " + ", ".join("{%s}" % u for u in unknown)
    if not _PIECE.search(pattern):
        return "The code needs a piece such as {year}, or every file would go in the same folder."
    if re.search(r'[<>:"\\|?*]', _PIECE.sub("", pattern)):
        return 'The code cannot contain  < > : " \\ | ? *   (use / for a sub-folder)'
    return None


@dataclass
class Move:
    """One file and the folder it will go to."""

    source: Path
    when: Optional[datetime]
    found_by: str
    target: Path
    note: str = ""          # "already there" when an identical file is in place

    @property
    def ok(self) -> bool:
        return not self.note


# ------------------------------------------------------------------ dates
def best_date(path: Path, use_file_date: bool = True):
    """``(datetime or None, how it was found)`` for one file."""
    suffix = path.suffix.lower()
    if suffix in PHOTO_EXTENSIONS:
        taken = photo_facts(path)[0]
        if taken:
            return taken, SOURCE_TAKEN
    if suffix in VIDEO_EXTENSIONS:
        recorded = creation_time(path)
        if recorded:
            return recorded, SOURCE_VIDEO
    if use_file_date:
        try:
            return datetime.fromtimestamp(path.stat().st_mtime), SOURCE_FILE
        except OSError:
            pass
    return None, SOURCE_NONE


def folder_for(path: Path, when: Optional[datetime], pattern: str) -> Path:
    """The dated folder (relative) a file goes to."""
    if when is None:
        return Path(NO_DATE_FOLDER)
    kind = "Videos" if path.suffix.lower() in VIDEO_EXTENSIONS else (
        "Photos" if path.suffix.lower() in PHOTO_EXTENSIONS else "Other files")
    values: Dict[str, str] = {
        "year": f"{when.year:04d}", "month": f"{when.month:02d}", "monthname": MONTHS[when.month - 1],
        "mon": MONTHS[when.month - 1][:3], "day": f"{when.day:02d}", "weekday": DAYS[when.weekday()],
        "date": when.strftime("%Y-%m-%d"), "kind": kind, "ext": path.suffix.lstrip(".").lower() or "none",
    }
    text = _PIECE.sub(lambda m: values.get(m.group(1), m.group(0)), pattern)
    parts = [safe_filename(part, fallback="_") for part in text.replace("\\", "/").split("/") if part.strip()]
    return Path(*parts) if parts else Path(NO_DATE_FOLDER)


# --------------------------------------------------------------- planning
def plan_sort(options: SortOptions, progress: Progress = lambda *_: None,
              cancel_event: Optional[threading.Event] = None) -> List[Move]:
    """Every file, its date and where it goes; nothing is moved."""
    cancel_event = cancel_event or threading.Event()
    progress(0.0, "listing the files")
    extensions = () if options.all_files else MEDIA_EXTENSIONS
    files = walk_files(options.folders, options.recursive, extensions, cancel_event=cancel_event)
    plan: List[Move] = []
    taken: Dict[str, Path] = {}
    for index, path in enumerate(files, start=1):
        if cancel_event.is_set():
            raise BatchCancelled()
        when, found_by = best_date(path, options.use_file_date)
        target = Path(options.target) / folder_for(path, when, options.pattern) / path.name
        move = Move(path, when, found_by, target)
        if path.resolve().parent == target.parent.resolve():
            move.note = "already in its place"
        elif target.exists() and same_content(path, target, cancel_event):
            move.note = "an identical file is already there"
        else:
            key = str(target).casefold()
            if key in taken:
                # two files with the same name for the same folder: the second one gets (2)
                move.target = _free_name(target, taken)
            taken[str(move.target).casefold()] = move.target
        plan.append(move)
        progress(index / max(1, len(files)), path.name)
    return plan


def _free_name(target: Path, taken: Dict[str, Path]) -> Path:
    counter = 2
    while True:
        candidate = target.with_name(f"{target.stem} ({counter}){target.suffix}")
        if str(candidate).casefold() not in taken and not candidate.exists():
            return candidate
        counter += 1


def summary_text(plan: List[Move], action: str = MOVE) -> str:
    if not plan:
        return "No photo or video found."
    going = [m for m in plan if m.ok]
    folders = {m.target.parent for m in going}
    undated = sum(1 for m in going if m.when is None)
    verb = "copied" if action == COPY else "moved"
    text = f"{len(going)} file(s) will be {verb} into {len(folders)} folder(s)."
    if undated:
        text += f" {undated} have no date and go to '{NO_DATE_FOLDER}'."
    left = len(plan) - len(going)
    if left:
        text += f" {left} left where they are."
    return text


# ----------------------------------------------------------------- acting
def apply_sort(plan: List[Move], options: SortOptions, progress: Progress = lambda *_: None,
               cancel_event: Optional[threading.Event] = None,
               on_log: Callable[[str, str], None] = lambda *_: None,
               journal_dir: Optional[Path] = None) -> Dict[str, int]:
    cancel_event = cancel_event or threading.Event()
    going = [m for m in plan if m.ok]
    journal = Journal(tool=TOOL)
    result = {"done": 0, "failed": 0}
    try:
        for index, move in enumerate(going, start=1):
            if cancel_event.is_set():
                break
            try:
                landed = transfer(move.source, move.target, options.action)
                journal.add(options.action, move.source, landed)
                result["done"] += 1
            except FileOpError as exc:
                result["failed"] += 1
                on_log("error", str(exc))
            progress(index / max(1, len(going)), move.source.name)
    finally:
        if journal.entries:
            save_journal(journal, journal_dir)
    return result
