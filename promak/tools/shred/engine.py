"""Deleting files so that they cannot be brought back.

Each file is written over with random bytes (once, or three times), forced
to the disk, renamed to a meaningless name, cut to nothing, then deleted.
On a classic hard disk that makes the old content unreadable to recovery
programs.

**What cannot be promised** (and the screen says so plainly): on SSDs,
USB sticks and memory cards the drive itself decides where the bytes go,
and may keep old copies in spare cells; in folders kept in sync with an
online storage service, earlier versions may be kept on the service and
in its recycle bin; snapshots, backups and shadow copies are not touched.
For those, full-disk encryption is the real answer.

Folders that hold the system or a whole drive are refused.  There is no
undo - that is the point - so the screen asks twice.  Nothing here imports Qt.
"""

from __future__ import annotations

import logging
import os
import secrets
import stat
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from promak.core.batch import BatchCancelled
from promak.core.fileops import FileOpError
from promak.core.imaging import human_size

log = logging.getLogger(__name__)

PASSES = [("1 pass of random data (enough for today's disks)", 1), ("3 passes (slower)", 3)]
CONFIRM_WORD = "DELETE"

WARNING = (
    "Overwriting works on classic hard disks. On SSDs, USB sticks and memory cards the drive decides where "
    "data really goes and may keep old copies Promak cannot reach; in folders synced with an online storage "
    "service, older versions may stay on the service. Backups and snapshots are not touched. For those, "
    "encrypting the whole disk is the real protection."
)

_CHUNK = 1024 * 1024
Progress = Callable[[float, str], None]


@dataclass
class ShredOptions:
    items: List[Path] = field(default_factory=list)
    passes: int = 1
    remove_folders: bool = True      # the folders themselves go too, once empty

    def validate(self) -> Optional[str]:
        if not self.items:
            return "Add the files or folders to delete."
        for item in self.items:
            problem = forbidden(Path(item))
            if problem:
                return problem
        return None


# ------------------------------------------------------------------ safety
def _protected_folders() -> List[Path]:
    found = [Path.home()]
    if sys.platform.startswith("win"):
        for name in ("SystemRoot", "WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramData", "APPDATA",
                     "LOCALAPPDATA", "USERPROFILE"):
            value = os.environ.get(name)
            if value:
                found.append(Path(value))
    else:
        found += [Path(p) for p in ("/", "/bin", "/boot", "/etc", "/lib", "/opt", "/sbin", "/usr", "/var",
                                    "/System", "/Library", "/Applications")]
    for name in ("Desktop", "Documents", "Downloads", "Pictures", "Music", "Videos"):
        found.append(Path.home() / name)
    found.append(Path(__file__).resolve().parents[3])    # Promak itself
    return found


def forbidden(path: Path) -> str:
    """Why ``path`` must not be wiped ('' when it may be)."""
    if not path.exists():
        return f"This no longer exists: {path}"
    resolved = path.resolve()
    if resolved == Path(resolved.anchor):
        return f"{path} is a whole drive: choose the files or folders inside it."
    for protected in _protected_folders():
        try:
            if resolved == protected.resolve():
                return f"{path} is a folder the computer or Promak needs (or a whole personal folder): " \
                       "choose the files or folders inside it."
        except OSError:
            continue
    if path.is_symlink():
        return f"{path} is a link: open it and choose what it points to."
    return ""


# ----------------------------------------------------------------- listing
def collect(items: List[Path]) -> Tuple[List[Path], List[Path]]:
    """``(every file, every folder)`` to wipe; links are never followed."""
    files: List[Path] = []
    folders: List[Path] = []
    for item in items:
        item = Path(item)
        if item.is_file() or item.is_symlink():
            files.append(item)
        elif item.is_dir():
            for root, dirs, names in os.walk(item, topdown=False, followlinks=False):
                for name in names:
                    files.append(Path(root) / name)
                for name in dirs:
                    folder = Path(root) / name
                    if folder.is_symlink():
                        files.append(folder)
                    else:
                        folders.append(folder)
            folders.append(item)
    return files, folders


def total_size(files: List[Path]) -> int:
    size = 0
    for file in files:
        try:
            if not file.is_symlink():
                size += file.stat().st_size
        except OSError:
            pass
    return size


# ----------------------------------------------------------------- wiping
def _writable(path: Path) -> None:
    try:
        mode = path.stat().st_mode
        if not mode & stat.S_IWRITE:
            os.chmod(path, mode | stat.S_IWRITE)
    except OSError:
        pass


def wipe_file(path: Path, passes: int = 1, cancel_event: Optional[threading.Event] = None,
              on_bytes: Callable[[int], None] = lambda n: None) -> None:
    """Overwrite, rename, truncate and delete one file."""
    if path.is_symlink():
        path.unlink()           # a link is removed, what it points to is left alone
        return
    _writable(path)
    size = path.stat().st_size
    with open(path, "r+b", buffering=0) as handle:
        for _ in range(max(1, passes)):
            handle.seek(0)
            left = size
            while left > 0:
                if cancel_event is not None and cancel_event.is_set():
                    raise BatchCancelled()
                block = min(_CHUNK, left)
                handle.write(secrets.token_bytes(block))
                left -= block
                on_bytes(block)
            handle.flush()
            os.fsync(handle.fileno())
        handle.truncate(0)
        os.fsync(handle.fileno())
    hidden = path.with_name(secrets.token_hex(8))
    os.replace(path, hidden)
    hidden.unlink()


def shred(options: ShredOptions, progress: Progress = lambda *_: None,
          cancel_event: Optional[threading.Event] = None,
          on_log: Callable[[str, str], None] = lambda *_: None) -> Dict[str, int]:
    problem = options.validate()
    if problem:
        raise FileOpError(problem)
    cancel = cancel_event or threading.Event()
    files, folders = collect(options.items)
    work = max(1, total_size(files) * max(1, options.passes))
    done_bytes = [0]
    result = {"done": 0, "failed": 0, "bytes": 0, "folders": 0}

    def advance(count: int) -> None:
        done_bytes[0] += count
        progress(done_bytes[0] / work, "")

    for file in files:
        if cancel.is_set():
            raise BatchCancelled()
        try:
            size = file.stat().st_size if not file.is_symlink() else 0
            wipe_file(file, options.passes, cancel, advance)
            result["done"] += 1
            result["bytes"] += size
            on_log("info", f"Deleted for good: {file}")
        except BatchCancelled:
            raise
        except OSError as exc:
            result["failed"] += 1
            on_log("error", f"{file}: {exc.strerror or exc} (is it open in another program?)")
    if options.remove_folders:
        for folder in folders:
            try:
                folder.rmdir()
                result["folders"] += 1
            except OSError:
                pass   # not empty: a file in it could not be deleted
    return result


def describe(files: List[Path]) -> str:
    return f"{len(files)} file(s), {human_size(total_size(files))}"
