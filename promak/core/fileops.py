"""Moving, copying and binning files safely, with an undo.

Used by the tools whose job is to touch the user's own files: the
duplicate finder, the photo sorter, the folder comparison.  Every move or
copy is written to a small journal, so the last run can be undone; files
are sent to the Recycle Bin rather than deleted.

Nothing here imports Qt.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Sequence

from promak.core.batch import BatchCancelled
from promak.core.imaging import ImageToolError
from promak.core.paths import app_data_dir, unique_path

log = logging.getLogger(__name__)

MOVE = "move"
COPY = "copy"
_CHUNK = 1024 * 1024


class FileOpError(ImageToolError):
    """A problem with the user's files, told in plain words."""


# ------------------------------------------------------------------ listing
def walk_files(folders: Iterable[Path], recursive: bool = True, extensions: Sequence[str] = (),
               include_hidden: bool = False, cancel_event: Optional[threading.Event] = None) -> List[Path]:
    """Every file inside ``folders`` (and their sub-folders), each once."""
    wanted = tuple(e.lower() for e in extensions)
    seen = set()
    found: List[Path] = []
    for folder in folders:
        folder = Path(folder)
        if not folder.is_dir():
            raise FileOpError(f"This folder does not exist: {folder}")
        for root, dirs, files in os.walk(folder):
            if cancel_event is not None and cancel_event.is_set():
                raise BatchCancelled()
            if not include_hidden:
                dirs[:] = [d for d in dirs if not d.startswith(".")]
            dirs.sort()
            if not recursive:
                dirs[:] = []
            for name in sorted(files):
                if not include_hidden and name.startswith("."):
                    continue
                if wanted and os.path.splitext(name)[1].lower() not in wanted:
                    continue
                path = Path(root) / name
                key = os.path.normcase(str(path.resolve()))
                if key not in seen:
                    seen.add(key)
                    found.append(path)
    return found


# ------------------------------------------------------------------ hashing
def file_hash(path: Path, limit: int = 0, cancel_event: Optional[threading.Event] = None) -> str:
    """BLAKE2 fingerprint of a file (only the first ``limit`` bytes if given)."""
    digest = hashlib.blake2b(digest_size=20)
    read = 0
    with open(path, "rb") as handle:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise BatchCancelled()
            size = _CHUNK if not limit else min(_CHUNK, limit - read)
            if size <= 0:
                break
            block = handle.read(size)
            if not block:
                break
            digest.update(block)
            read += len(block)
    return digest.hexdigest()


def same_content(a: Path, b: Path, cancel_event: Optional[threading.Event] = None) -> bool:
    """True when two files hold exactly the same bytes."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
    except OSError:
        return False
    return file_hash(a, cancel_event=cancel_event) == file_hash(b, cancel_event=cancel_event)


# --------------------------------------------------------------- the bin
def recycle_bin_available() -> bool:
    try:
        import send2trash  # noqa: F401
    except ImportError:
        return False
    return True


def to_recycle_bin(path: Path) -> None:
    """Send one file or folder to the Recycle Bin (never delete it outright)."""
    try:
        from send2trash import send2trash
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise FileOpError("send2trash is missing, so nothing can be put in the Recycle Bin. "
                          "Run install_windows.bat again, or:  pip install -U send2trash") from exc
    try:
        send2trash(str(path))
    except Exception as exc:
        raise FileOpError(f"'{Path(path).name}' could not be put in the Recycle Bin: {exc}") from exc


# ------------------------------------------------------------- journal
@dataclass
class Journal:
    """What a run moved or copied, so it can be undone."""

    tool: str
    when: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    entries: List[List[str]] = field(default_factory=list)   # [MOVE or COPY, source, target]

    def add(self, action: str, source: Path, target: Path) -> None:
        self.entries.append([action, str(source), str(target)])

    @property
    def count(self) -> int:
        return len(self.entries)


def journal_file(tool: str, folder: Optional[Path] = None) -> Path:
    base = Path(folder) if folder else app_data_dir()
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{tool}-last.json"


def save_journal(journal: Journal, folder: Optional[Path] = None) -> None:
    try:
        journal_file(journal.tool, folder).write_text(
            json.dumps(journal.__dict__, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:  # pragma: no cover - the undo is a bonus
        log.warning("Could not write the undo journal", exc_info=True)


def load_journal(tool: str, folder: Optional[Path] = None) -> Optional[Journal]:
    path = journal_file(tool, folder)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Journal(tool=data["tool"], when=data["when"], entries=list(data["entries"]))
    except (OSError, ValueError, KeyError):
        return None


def forget_journal(tool: str, folder: Optional[Path] = None) -> None:
    try:
        journal_file(tool, folder).unlink()
    except OSError:
        pass


# --------------------------------------------------------- move and copy
def transfer(source: Path, target: Path, action: str = MOVE, overwrite: bool = False) -> Path:
    """Move or copy one file to ``target``; returns where it really went.

    A file already at ``target`` is never replaced unless asked: the new
    one gets a free name such as ``photo (2).jpg``.  A copy keeps the dates.
    """
    source, target = Path(source), Path(target)
    if not source.exists():
        raise FileOpError(f"The file no longer exists: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        target = unique_path(target)
    try:
        if action == COPY:
            shutil.copy2(source, target)
        else:
            shutil.move(str(source), str(target))
    except PermissionError as exc:
        raise FileOpError(f"'{source.name}' is in use or read-only: close it in the other program and retry.") \
            from exc
    except OSError as exc:
        raise FileOpError(f"'{source.name}' could not be {'copied' if action == COPY else 'moved'}: {exc}") from exc
    return target


def undo_journal(journal: Journal, on_log: Optional[Callable[[str, str], None]] = None) -> int:
    """Put moved files back and remove copies; returns how many were undone.

    A copy is removed only when it is still the same size as its original,
    so a copy edited since is kept.  A moved file whose old place is taken
    goes back under a free name.
    """
    say = on_log or (lambda level, message: None)
    undone = 0
    for action, source, target in reversed(journal.entries):
        source_path, target_path = Path(source), Path(target)
        try:
            if action == COPY:
                if target_path.exists():
                    if source_path.exists() and source_path.stat().st_size != target_path.stat().st_size:
                        say("warning", f"Kept {target_path.name}: it changed after being copied.")
                        continue
                    target_path.unlink()
                    _remove_empty_parents(target_path.parent)
                    undone += 1
            else:
                if not target_path.exists():
                    say("warning", f"{target_path.name} is no longer where it was moved.")
                    continue
                back = transfer(target_path, source_path, MOVE)
                _remove_empty_parents(target_path.parent)
                undone += 1
                if back != source_path:
                    say("warning", f"{source_path.name} came back as {back.name}: its old name was taken.")
        except (OSError, FileOpError) as exc:
            say("error", f"{target_path.name}: {exc}")
    return undone


def _remove_empty_parents(folder: Path, levels: int = 3) -> None:
    """Remove folders a run created and left empty (never anything else)."""
    for _ in range(levels):
        try:
            folder.rmdir()  # fails when not empty: exactly what we want
        except OSError:
            return
        folder = folder.parent
