"""Making and opening archives: ZIP, 7z and TAR.

* **Make**: files and folders into one ZIP (with an AES-256 password if you
  like, through pyzipper, MIT) or 7z (py7zr, LGPL - used as a library; the
  7z password also hides the file names).
* **Open**: ZIP, 7z and TAR (.tar, .tar.gz, .tgz, .tar.bz2, .tar.xz) are
  listed, and extracted into a folder of their own.
* **Safe**: an entry that would land outside the destination folder (an
  absolute path, ``..``) or that is a link or a device is refused, so a
  malicious archive cannot write anywhere else; nothing already there is
  overwritten unless asked.

Nothing here imports Qt.  The originals are never changed.
"""

from __future__ import annotations

import logging
import os
import shutil
import tarfile
import threading
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable, List, Optional, Sequence, Tuple

from promak.core.batch import BatchCancelled
from promak.core.imaging import ImageToolError, human_size
from promak.core.paths import safe_filename, unique_path

log = logging.getLogger(__name__)

ZIP = "zip"
SEVEN = "7z"
FORMATS = [("ZIP - opens everywhere", ZIP), ("7z - smaller, the password also hides the file names", SEVEN)]
LEVELS = [("Normal", 6), ("Fast (larger file)", 1), ("Smallest (slower)", 9), ("Store only (no compression)", 0)]

TAR_SUFFIXES = (".tar", ".tgz", ".tbz", ".tbz2", ".txz", ".tar.gz", ".tar.bz2", ".tar.xz")
ARCHIVE_EXTENSIONS = (".zip", ".7z") + TAR_SUFFIXES

Progress = Callable[[float, str], None]


class ArchiveError(ImageToolError):
    """An archive problem told in plain words."""


@dataclass
class Entry:
    """One file inside an archive."""

    name: str                 # path inside the archive, with "/"
    size: int
    when: Optional[datetime] = None
    folder: bool = False
    encrypted: bool = False
    problem: str = ""

    @property
    def when_text(self) -> str:
        return self.when.strftime("%Y-%m-%d %H:%M") if self.when else ""


@dataclass
class MakeOptions:
    items: List[Path] = field(default_factory=list)
    target: Optional[Path] = None             # the archive to write
    fmt: str = ZIP
    level: int = 6
    password: str = ""
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if not self.items:
            return "Add the files and folders that go in the archive."
        for item in self.items:
            if not Path(item).exists():
                return f"This no longer exists: {item}"
        if not self.target:
            return "Choose where the archive is saved."
        if self.password and len(self.password) < 4:
            return "Use a password of at least 4 characters - or none."
        target = Path(self.target).resolve()
        for item in self.items:
            if Path(item).is_dir() and Path(item).resolve() in target.parents:
                return "The archive cannot be saved inside a folder that goes into it."
        return None


def archive_kind(path: Path) -> Optional[str]:
    name = Path(path).name.lower()
    if name.endswith(".zip"):
        return ZIP
    if name.endswith(".7z"):
        return SEVEN
    if name.endswith(TAR_SUFFIXES):
        return "tar"
    return None


def archive_stem(path: Path) -> str:
    """'photos.tar.gz' -> 'photos'."""
    name = Path(path).name
    for suffix in sorted(ARCHIVE_EXTENSIONS, key=len, reverse=True):
        if name.lower().endswith(suffix):
            return name[: -len(suffix)] or "archive"
    return Path(path).stem


def require_pyzipper():
    try:
        import pyzipper
    except ImportError as exc:  # pragma: no cover - depends on the machine
        raise ArchiveError("pyzipper is missing. Run install_windows.bat again, or:  pip install -U pyzipper") from exc
    return pyzipper


def require_py7zr():
    try:
        import py7zr
    except ImportError as exc:  # pragma: no cover
        raise ArchiveError("py7zr is missing, so 7z files cannot be used. Run install_windows.bat again, "
                           "or:  pip install -U py7zr") from exc
    return py7zr


# ------------------------------------------------------------------ safety
def unsafe_reason(name: str) -> str:
    """Why an entry name must not be extracted ('' when it is fine)."""
    text = name.replace("\\", "/")
    if not text or text.startswith("/") or (len(text) > 1 and text[1] == ":"):
        return "an absolute path"
    if any(part == ".." for part in PurePosixPath(text).parts):
        return "a path that climbs out of the folder"
    return ""


def _inside(root: Path, name: str) -> Path:
    target = (root / name.replace("\\", "/")).resolve()
    if root.resolve() != target and root.resolve() not in target.parents:
        raise ArchiveError(f"'{name}' would land outside the destination folder: the archive is refused.")
    return target


# ------------------------------------------------------------------ listing
def list_archive(path: Path, password: str = "") -> List[Entry]:
    kind = archive_kind(path)
    try:
        if kind == ZIP:
            pyzipper = require_pyzipper()
            with pyzipper.AESZipFile(str(path)) as archive:
                return [Entry(info.filename, info.file_size, datetime(*info.date_time), info.is_dir(),
                              bool(info.flag_bits & 0x1), unsafe_reason(info.filename)) for info in archive.infolist()]
        if kind == SEVEN:
            py7zr = require_py7zr()
            with py7zr.SevenZipFile(str(path), "r", password=password or None) as archive:
                entries = []
                for info in archive.list():
                    entries.append(Entry(info.filename, int(info.uncompressed or 0), info.creationtime,
                                         bool(info.is_directory), archive.needs_password(),
                                         unsafe_reason(info.filename)))
                return entries
        if kind == "tar":
            with tarfile.open(str(path)) as archive:
                entries = []
                for member in archive.getmembers():
                    problem = unsafe_reason(member.name)
                    if not (member.isfile() or member.isdir()):
                        problem = problem or "a link or a device, not a file"
                    entries.append(Entry(member.name, member.size, datetime.fromtimestamp(member.mtime),
                                         member.isdir(), False, problem))
                return entries
    except ArchiveError:
        raise
    except Exception as exc:
        text = str(exc).lower()
        if kind == SEVEN and password:
            # with hidden names, a wrong password only shows as unreadable headers
            raise ArchiveError("The password is missing or not right for this archive.") from exc
        if "password" in text:
            raise ArchiveError("This archive is protected: type its password.") from exc
        raise ArchiveError(f"This file cannot be read as an archive ({exc}). It may be damaged.") from exc
    raise ArchiveError(f"'{Path(path).name}' is not a ZIP, 7z or TAR archive.")


def describe(entries: Sequence[Entry]) -> str:
    files = [e for e in entries if not e.folder]
    return f"{len(files)} file(s), {human_size(sum(e.size for e in files))}"


# --------------------------------------------------------------- extracting
def extract_archive(path: Path, destination: Path, password: str = "", own_folder: bool = True,
                    overwrite: bool = False, progress: Progress = lambda *_: None,
                    cancel_event: Optional[threading.Event] = None) -> Tuple[Path, int]:
    """Extract everything safely; returns ``(folder used, files written)``."""
    cancel_event = cancel_event or threading.Event()
    entries = list_archive(path, password)
    bad = [e for e in entries if e.problem]
    if bad:
        raise ArchiveError(f"The archive holds '{bad[0].name}' ({bad[0].problem}): nothing was extracted. "
                           "It may have been made to do harm.")
    root = Path(destination)
    if own_folder:
        root = root / safe_filename(archive_stem(path), fallback="archive")
        if root.exists() and not overwrite:
            root = unique_path(root)
    created = not root.exists()
    root.mkdir(parents=True, exist_ok=True)
    kind = archive_kind(path)
    total = sum(e.size for e in entries) or 1
    written = 0
    done_bytes = 0

    def place(name: str) -> Path:
        target = _inside(root, name)
        if target.exists() and not overwrite:
            target = unique_path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    try:
        if kind == ZIP:
            pyzipper = require_pyzipper()
            with pyzipper.AESZipFile(str(path)) as archive:
                if password:
                    archive.setpassword(password.encode("utf-8"))
                locked = next((i for i in archive.infolist() if i.flag_bits & 0x1 and not i.is_dir()), None)
                if locked is not None:
                    if not password:
                        raise ArchiveError("This archive is protected: type its password.")
                    with archive.open(locked) as probe:   # a wrong password fails here, before anything is written
                        probe.read(1)
                for info in archive.infolist():
                    if cancel_event.is_set():
                        raise BatchCancelled()
                    if info.is_dir():
                        _inside(root, info.filename).mkdir(parents=True, exist_ok=True)
                        continue
                    target = place(info.filename)
                    with archive.open(info) as source, open(target, "wb") as out:
                        shutil.copyfileobj(source, out, 1024 * 1024)
                    _set_time(target, datetime(*info.date_time))
                    written += 1
                    done_bytes += info.file_size
                    progress(done_bytes / total, info.filename)
        elif kind == SEVEN:
            py7zr = require_py7zr()
            with py7zr.SevenZipFile(str(path), "r", password=password or None) as archive:
                if archive.needs_password() and not password:
                    raise ArchiveError("This archive is protected: type its password.")
                staging = root / f".promak-extract-{os.getpid()}"
                archive.extractall(path=str(staging))
            for file in sorted(p for p in staging.rglob("*") if p.is_file()):
                name = file.relative_to(staging).as_posix()
                target = place(name)
                shutil.move(str(file), str(target))
                written += 1
            shutil.rmtree(staging, ignore_errors=True)
            progress(1.0, "")
        else:
            with tarfile.open(str(path)) as archive:
                for member in archive.getmembers():
                    if cancel_event.is_set():
                        raise BatchCancelled()
                    if member.isdir():
                        _inside(root, member.name).mkdir(parents=True, exist_ok=True)
                        continue
                    target = place(member.name)
                    source = archive.extractfile(member)
                    if source is None:
                        continue
                    with source, open(target, "wb") as out:
                        shutil.copyfileobj(source, out, 1024 * 1024)
                    _set_time(target, datetime.fromtimestamp(member.mtime))
                    written += 1
                    done_bytes += member.size
                    progress(done_bytes / total, member.name)
    except (ArchiveError, BatchCancelled):
        _forget(root, created)
        raise
    except RuntimeError as exc:
        _forget(root, created)
        if "password" in str(exc).lower() or "encrypted" in str(exc).lower():
            raise ArchiveError("The password is missing or not right for this archive.") from exc
        raise ArchiveError(f"The archive could not be extracted ({exc}).") from exc
    except Exception as exc:
        _forget(root, created)
        text = str(exc).lower()
        if "password" in text or "bad mac" in text or "crc" in text:
            raise ArchiveError("The password is missing or not right for this archive.") from exc
        raise ArchiveError(f"The archive could not be extracted ({exc}).") from exc
    return root, written


def _forget(root: Path, created: bool) -> None:
    """A failed extraction leaves nothing behind in a folder it made itself."""
    if created:
        shutil.rmtree(root, ignore_errors=True)


def _set_time(path: Path, when: datetime) -> None:
    try:
        stamp = when.timestamp()
        os.utime(path, (stamp, stamp))
    except (OSError, ValueError, OverflowError):
        pass


# ------------------------------------------------------------------ making
def plan_items(items: Sequence[Path]) -> List[Tuple[Path, str]]:
    """``(file on disk, name inside the archive)`` for everything that goes in.

    A folder goes in with its own name on top (``Holiday/IMG_1.jpg``), as
    when it is dragged into an archive by hand.
    """
    pairs: List[Tuple[Path, str]] = []
    seen = set()
    for item in items:
        item = Path(item)
        if item.is_dir():
            for root, dirs, files in os.walk(item):
                dirs.sort()
                for name in sorted(files):
                    file = Path(root) / name
                    arcname = (Path(item.name) / file.relative_to(item)).as_posix()
                    if arcname.lower() not in seen:
                        seen.add(arcname.lower())
                        pairs.append((file, arcname))
        elif item.is_file():
            arcname = item.name
            counter = 2
            while arcname.lower() in seen:
                arcname = f"{item.stem} ({counter}){item.suffix}"
                counter += 1
            seen.add(arcname.lower())
            pairs.append((item, arcname))
    return pairs


def make_archive(options: MakeOptions, progress: Progress = lambda *_: None,
                 cancel_event: Optional[threading.Event] = None) -> Tuple[Path, int]:
    """Write the archive; returns ``(archive, files in it)``."""
    problem = options.validate()
    if problem:
        raise ArchiveError(problem)
    cancel_event = cancel_event or threading.Event()
    pairs = plan_items(options.items)
    if not pairs:
        raise ArchiveError("There is no file to put in the archive (the folders are empty).")
    target = Path(options.target)
    if target.suffix.lower() != f".{options.fmt}":
        target = target.with_name(target.name + f".{options.fmt}")
    if target.exists() and not options.overwrite:
        target = unique_path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    scratch = target.with_name(target.name + ".part")
    total = sum(p.stat().st_size for p, _n in pairs) or 1
    done = 0
    try:
        if options.fmt == SEVEN:
            py7zr = require_py7zr()
            filters = None if options.level else [{"id": py7zr.FILTER_COPY}]
            with py7zr.SevenZipFile(str(scratch), "w", password=options.password or None,
                                    header_encryption=bool(options.password), filters=filters) as archive:
                for file, arcname in pairs:
                    if cancel_event.is_set():
                        raise BatchCancelled()
                    archive.write(str(file), arcname)
                    done += file.stat().st_size
                    progress(done / total, arcname)
        else:
            pyzipper = require_pyzipper()
            method = zipfile.ZIP_STORED if options.level == 0 else zipfile.ZIP_DEFLATED
            kwargs = {"compression": method}
            if options.level:
                kwargs["compresslevel"] = options.level
            if options.password:
                kwargs["encryption"] = pyzipper.WZ_AES
            with pyzipper.AESZipFile(str(scratch), "w", **kwargs) as archive:
                if options.password:
                    archive.setpassword(options.password.encode("utf-8"))
                    archive.setencryption(pyzipper.WZ_AES, nbits=256)
                for file, arcname in pairs:
                    if cancel_event.is_set():
                        raise BatchCancelled()
                    archive.write(str(file), arcname)
                    done += file.stat().st_size
                    progress(done / total, arcname)
        scratch.replace(target)
    finally:
        if scratch.exists():
            scratch.unlink()
    return target, len(pairs)
