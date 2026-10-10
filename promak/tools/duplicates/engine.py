"""Finding duplicate files and similar pictures.

Two kinds of search:

* **exact** - files with the very same bytes.  Files are first grouped by
  size (two files of different size cannot be equal), then by a
  fingerprint of their first 64 KB, and only then fully fingerprinted, so
  a folder of thousands of photos is read once at most;
* **similar** - pictures that look alike even when their files differ (a
  copy resized for e-mail, saved again, slightly cropped).  Each picture
  gets a perceptual fingerprint (``imagehash``, BSD) and pictures whose
  fingerprints are close enough end up in the same group.  The similarity
  slider says how close is close enough.

In every group one file is kept - the largest or the oldest by default -
and the others are marked to go.  Nothing is deleted: the marked files go
to the Recycle Bin (``send2trash``, BSD) or are moved to a folder of your
choice, and a move can be undone.  Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from promak.core.batch import BatchCancelled
from promak.core.fileops import (
    MOVE,
    FileOpError,
    Journal,
    file_hash,
    save_journal,
    to_recycle_bin,
    transfer,
    walk_files,
)
from promak.core.imaging import RASTER_EXTENSIONS, human_size

log = logging.getLogger(__name__)

TOOL = "duplicates"

EXACT = "exact"
SIMILAR = "similar"
MODES = [
    ("Exact copies - the very same file, any kind", EXACT),
    ("Similar pictures - resized, saved again, slightly changed", SIMILAR),
]

KEEP_LARGEST = "largest"
KEEP_OLDEST = "oldest"
KEEP_NEWEST = "newest"
KEEP_SHORTEST = "shortest"
KEEP_RULES = [
    ("The largest (best quality)", KEEP_LARGEST),
    ("The oldest (the original)", KEEP_OLDEST),
    ("The newest", KEEP_NEWEST),
    ("The one with the shortest path", KEEP_SHORTEST),
]

TO_BIN = "bin"
TO_FOLDER = "folder"
ACTIONS = [
    ("Put them in the Recycle Bin", TO_BIN),
    ("Move them to a folder (can be undone)", TO_FOLDER),
]

SIMILAR_EXTENSIONS = RASTER_EXTENSIONS
_PREFIX = 64 * 1024

Progress = Callable[[float, str], None]


@dataclass
class DuplicateOptions:
    folders: List[Path] = field(default_factory=list)
    recursive: bool = True
    mode: str = EXACT
    similarity: int = 90            # percent, for SIMILAR
    min_kb: int = 1                 # smaller files are ignored
    keep: str = KEEP_LARGEST
    action: str = TO_BIN
    move_to: Optional[Path] = None

    def validate(self) -> Optional[str]:
        if not self.folders:
            return "Add at least one folder to look in."
        missing = [str(f) for f in self.folders if not Path(f).is_dir()]
        if missing:
            return f"This folder does not exist: {missing[0]}"
        if self.mode == SIMILAR and not 50 <= self.similarity <= 100:
            return "The similarity goes from 50 to 100 percent."
        return None

    def validate_action(self) -> Optional[str]:
        if self.action == TO_FOLDER:
            if not self.move_to:
                return "Choose the folder the duplicates are moved to."
            target = Path(self.move_to).resolve()
            for folder in self.folders:
                if target == Path(folder).resolve():
                    return "Choose a folder other than the ones being searched."
        return None

    @property
    def max_distance(self) -> int:
        """How many of the 64 fingerprint bits may differ."""
        return max(0, round((100 - self.similarity) * 64 / 100))


@dataclass
class Entry:
    """One file of a group."""

    path: Path
    size: int
    modified: float
    pixels: int = 0              # width x height, pictures only
    remove: bool = False

    @property
    def date_text(self) -> str:
        return datetime.fromtimestamp(self.modified).strftime("%Y-%m-%d %H:%M")


@dataclass
class Group:
    entries: List[Entry]
    kind: str = EXACT

    @property
    def keeper(self) -> Optional[Entry]:
        kept = [e for e in self.entries if not e.remove]
        return kept[0] if kept else None

    @property
    def freed_bytes(self) -> int:
        return sum(e.size for e in self.entries if e.remove)


# --------------------------------------------------------------- searching
def find_duplicates(options: DuplicateOptions, progress: Progress = lambda *_: None,
                    cancel_event: Optional[threading.Event] = None) -> List[Group]:
    """Look in the folders; returns the groups, with the files to go marked."""
    cancel_event = cancel_event or threading.Event()
    extensions = SIMILAR_EXTENSIONS if options.mode == SIMILAR else ()
    progress(0.0, "listing the files")
    files = walk_files(options.folders, options.recursive, extensions, cancel_event=cancel_event)
    skip = set()
    if options.action == TO_FOLDER and options.move_to:
        # files moved away by an earlier run are not looked at again
        target = Path(options.move_to).resolve()
        skip = {f for f in files if target in f.resolve().parents}
    files = [f for f in files if f not in skip]
    if options.mode == SIMILAR:
        groups = _similar_groups(files, options, progress, cancel_event)
    else:
        groups = _exact_groups(files, options, progress, cancel_event)
    for group in groups:
        mark(group, options.keep)
    groups.sort(key=lambda g: -g.freed_bytes)
    progress(1.0, f"{len(groups)} group(s)")
    return groups


def _entry(path: Path) -> Optional[Entry]:
    try:
        stat = path.stat()
    except OSError:
        return None
    return Entry(path=path, size=stat.st_size, modified=stat.st_mtime)


def _exact_groups(files: Sequence[Path], options: DuplicateOptions, progress: Progress,
                  cancel_event: threading.Event) -> List[Group]:
    by_size: Dict[int, List[Entry]] = defaultdict(list)
    for path in files:
        entry = _entry(path)
        if entry is not None and entry.size >= options.min_kb * 1024:
            by_size[entry.size].append(entry)
    candidates = [group for group in by_size.values() if len(group) > 1]
    total = sum(len(group) for group in candidates) or 1
    done = 0
    groups: List[Group] = []
    for same_size in candidates:
        # a cheap first look at the start of each file, then the whole file
        by_prefix: Dict[str, List[Entry]] = defaultdict(list)
        for entry in same_size:
            if cancel_event.is_set():
                raise BatchCancelled()
            try:
                by_prefix[file_hash(entry.path, _PREFIX, cancel_event)].append(entry)
            except OSError:
                continue
        for same_start in by_prefix.values():
            if len(same_start) < 2:
                done += len(same_start)
                continue
            by_hash: Dict[str, List[Entry]] = defaultdict(list)
            for entry in same_start:
                try:
                    key = file_hash(entry.path, cancel_event=cancel_event) if entry.size > _PREFIX else "whole"
                except OSError:
                    continue
                by_hash[key].append(entry)
                done += 1
                progress(done / total, f"comparing {entry.path.name}")
            groups.extend(Group(sorted(g, key=lambda e: str(e.path).lower()), EXACT)
                          for g in by_hash.values() if len(g) > 1)
        progress(done / total, "")
    return groups


def require_imagehash():
    try:
        import imagehash
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise FileOpError("imagehash is missing, so similar pictures cannot be found. "
                          "Run install_windows.bat again, or:  pip install -U imagehash") from exc
    return imagehash


def picture_fingerprint(path: Path):
    """``(64-bit perceptual hash as an int, width x height)`` or ``None``."""
    imagehash = require_imagehash()
    from PIL import Image, ImageOps

    try:
        with Image.open(path) as opened:
            pixels = opened.size[0] * opened.size[1]
            opened.draft("RGB", (512, 512))  # JPEG: decode small, much faster
            image = ImageOps.exif_transpose(opened)
            fingerprint = imagehash.phash(image.convert("RGB"))
    except Exception:
        return None
    return int(str(fingerprint), 16), pixels


def _distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _similar_groups(files: Sequence[Path], options: DuplicateOptions, progress: Progress,
                    cancel_event: threading.Event) -> List[Group]:
    entries: List[Entry] = []
    prints: List[int] = []
    for index, path in enumerate(files, start=1):
        if cancel_event.is_set():
            raise BatchCancelled()
        entry = _entry(path)
        if entry is None or entry.size < options.min_kb * 1024:
            continue
        found = picture_fingerprint(path)
        if found is None:
            continue
        entry.pixels = found[1]
        entries.append(entry)
        prints.append(found[0])
        progress(0.9 * index / max(1, len(files)), f"looking at {path.name}")

    # pictures closer than the limit join the same group (union-find)
    parent = list(range(len(entries)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    limit = options.max_distance
    for i in range(len(entries)):
        if cancel_event.is_set():
            raise BatchCancelled()
        for j in range(i + 1, len(entries)):
            if _distance(prints[i], prints[j]) <= limit:
                parent[root(j)] = root(i)
    clusters: Dict[int, List[Entry]] = defaultdict(list)
    for index, entry in enumerate(entries):
        clusters[root(index)].append(entry)
    return [Group(sorted(c, key=lambda e: str(e.path).lower()), SIMILAR) for c in clusters.values() if len(c) > 1]


# ---------------------------------------------------------------- choosing
def mark(group: Group, rule: str) -> None:
    """Keep one file of the group by ``rule``; mark the others to go."""
    if rule == KEEP_OLDEST:
        best = min(group.entries, key=lambda e: (e.modified, len(str(e.path))))
    elif rule == KEEP_NEWEST:
        best = max(group.entries, key=lambda e: (e.modified, -len(str(e.path))))
    elif rule == KEEP_SHORTEST:
        best = min(group.entries, key=lambda e: (len(str(e.path)), e.modified))
    else:
        best = max(group.entries, key=lambda e: (e.pixels, e.size, -e.modified))
    for entry in group.entries:
        entry.remove = entry is not best


def marked(groups: Sequence[Group]) -> List[Entry]:
    return [entry for group in groups for entry in group.entries if entry.remove]


def summary_text(groups: Sequence[Group]) -> str:
    going = marked(groups)
    if not groups:
        return "No duplicate found."
    return (f"{len(groups)} group(s); {len(going)} file(s) marked to go, "
            f"{human_size(sum(e.size for e in going))} would be freed.")


# ---------------------------------------------------------------- acting
def check_groups(groups: Sequence[Group]) -> Optional[str]:
    """Refuse to act on a group where every file is marked to go."""
    for number, group in enumerate(groups, start=1):
        if group.entries and all(entry.remove for entry in group.entries):
            return (f"In group {number} every file is marked to go: keep at least one "
                    "(untick it) or nothing of it would be left.")
    return None


def remove_duplicates(groups: Sequence[Group], options: DuplicateOptions, progress: Progress = lambda *_: None,
                      cancel_event: Optional[threading.Event] = None,
                      on_log: Callable[[str, str], None] = lambda *_: None,
                      journal_dir: Optional[Path] = None) -> Dict[str, int]:
    """Bin or move every marked file; returns ``{"done": n, "failed": n}``."""
    problem = check_groups(groups) or options.validate_action()
    if problem:
        raise FileOpError(problem)
    cancel_event = cancel_event or threading.Event()
    going = marked(groups)
    journal = Journal(tool=TOOL)
    result = {"done": 0, "failed": 0, "bytes": 0}
    common = _common_root(options.folders)
    try:
        for index, entry in enumerate(going, start=1):
            if cancel_event.is_set():
                break
            try:
                if options.action == TO_FOLDER:
                    relative = _relative(entry.path, common)
                    target = transfer(entry.path, Path(options.move_to) / relative, MOVE)
                    journal.add(MOVE, entry.path, target)
                else:
                    to_recycle_bin(entry.path)
                result["done"] += 1
                result["bytes"] += entry.size
            except FileOpError as exc:
                result["failed"] += 1
                on_log("error", str(exc))
            progress(index / max(1, len(going)), entry.path.name)
    finally:
        if journal.entries:
            save_journal(journal, journal_dir)
    return result


def _common_root(folders: Sequence[Path]) -> Optional[Path]:
    import os

    try:
        return Path(os.path.commonpath([str(Path(f).resolve()) for f in folders]))
    except ValueError:  # different drives
        return None


def _relative(path: Path, root: Optional[Path]) -> Path:
    """Where a moved file goes inside the target folder: its own sub-path."""
    resolved = path.resolve()
    if root is not None:
        try:
            return resolved.relative_to(root)
        except ValueError:
            pass
    drive = resolved.drive.replace(":", "") or "root"
    return Path(drive, *resolved.parts[1:])
