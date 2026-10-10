"""Giving the folders - or the files - inside a folder sequential names.

    Holiday            ->  01 - Holiday
    Birthday           ->  02 - Birthday
    Work trip          ->  03 - Work trip

Three steps, kept apart so the screen can show the result before anything
is touched:

1. :func:`list_folders` reads the folders and puts them in order;
2. :func:`plan_renames` works out every new name and every problem;
3. :func:`apply_renames` renames, in two passes, so two folders can swap
   names ("01" and "02") without one overwriting the other.

Every renaming is written to a small journal, and :func:`undo_renames`
puts the old names back.  Nothing here imports Qt.

The same engine renames files (``RenameOptions.kind = KIND_FILES``): the
name is built for the part before the extension, and the extension is
always put back, so a file never stops opening.  Files get four more
pieces: ``{ext}``, ``{taken}`` (the date a photo was taken), ``{width}``
and ``{height}``.
"""

from __future__ import annotations

import functools
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from promak.core.paths import app_data_dir, safe_filename

log = logging.getLogger(__name__)

# --- what the user picks -------------------------------------------------
ORDER_NAME = "name"
ORDER_MODIFIED = "modified"
ORDER_CREATED = "created"
ORDER_MANUAL = "manual"
ORDER_TAKEN = "taken"          # files: the date a photo was taken

ORDERS = [
    ("By name (2 before 10)", ORDER_NAME),
    ("By date changed, oldest first", ORDER_MODIFIED),
    ("By date created, oldest first", ORDER_CREATED),
    ("As I arrange them", ORDER_MANUAL),
    ("By date taken (photos), oldest first", ORDER_TAKEN),
]

STYLE_NUMBER_NAME = "number_name"
STYLE_NAME_NUMBER = "name_number"
STYLE_NUMBER_ONLY = "number_only"
STYLE_TEXT_NUMBER = "text_number"
STYLE_CUSTOM = "custom"

STYLES = [
    ("Number, then the old name   (01 - Holiday)", STYLE_NUMBER_NAME),
    ("Old name, then the number   (Holiday - 01)", STYLE_NAME_NUMBER),
    ("Number only   (01)", STYLE_NUMBER_ONLY),
    ("My text and the number   (Project 01)", STYLE_TEXT_NUMBER),
    ("My own code   (PRJ-2026-001 Holiday)", STYLE_CUSTOM),
]

#: the pieces a custom code can be built from, as shown to the user
CODE_PIECES = [
    ("{n}", "the number (digits as set below); {n:3} always 3 digits: 001"),
    ("{name}", "the old name (without its old number, if that box is ticked)"),
    ("{original}", "the old name exactly as it is"),
    ("{name:upper}", "the old name in CAPITALS; also :lower and :title"),
    ("{letter}", "A, B, C ... Z, AA; {letter:lower} for a, b, c"),
    ("{roman}", "I, II, III, IV ...; {roman:lower} for i, ii, iii"),
    ("{date}", "the date the folder was last changed: 2026-10-10"),
    ("{year} {month} {day}", "the same date in pieces: 2026 10 10"),
    ("{today}", "today's date: 2026-10-10"),
    ("{parent}", "the name of the folder that holds them"),
    ("{total}", "how many folders are being numbered"),
]

#: the pieces of a code for files: the same, plus what a file knows of itself
FILE_CODE_PIECES = [
    ("{n}", "the number (digits as set below); {n:3} always 3 digits: 001"),
    ("{name}", "the old name without its extension (and without its old number, if ticked)"),
    ("{original}", "the old name without its extension, exactly as it is"),
    ("{name:upper}", "the old name in CAPITALS; also :lower and :title"),
    ("{ext}", "the extension: jpg, pdf... (the extension is always kept at the end anyway)"),
    ("{taken}", "the date a photo was taken: 2026-10-10; {taken:time} adds the hour"),
    ("{width} {height}", "the size of a picture in pixels: 4032 3024"),
    ("{date}", "the date the file was last changed: 2026-10-10"),
    ("{year} {month} {day}", "the same date in pieces: 2026 10 10"),
    ("{letter}", "A, B, C ... Z, AA; {letter:lower} for a, b, c"),
    ("{roman}", "I, II, III, IV ...; {roman:lower} for i, ii, iii"),
    ("{today}", "today's date: 2026-10-10"),
    ("{parent}", "the name of the folder that holds them"),
    ("{total}", "how many files are being renamed"),
]

FILE_CODE_EXAMPLES = [
    "{taken} {n:3}",
    "{parent} {n:3}",
    "{taken:%Y%m%d}_{name}",
    "{name} {width}x{height}",
    "IMG-{n:4}",
]

CODE_EXAMPLES = [
    "{n} - {name}",
    "PRJ-{year}-{n:3} {name}",
    "{date} {name}",
    "{parent} {n}",
    "{letter}. {name:upper}",
    "Chapter {roman} - {name}",
]

_PIECE = re.compile(r"\{(\w+)(?::([^{}]*))?\}")
_KNOWN_PIECES = {"n", "name", "original", "letter", "roman", "date", "year", "month", "day",
                 "today", "parent", "total", "ext", "taken", "width", "height"}

KIND_FOLDERS = "folders"
KIND_FILES = "files"

#: a number already at the start of a name, with what separates it
_LEADING_NUMBER = re.compile(r"^\s*\d+\s*[-_.)\]]*\s*")
_NATURAL_SPLIT = re.compile(r"(\d+)")


class RenameError(RuntimeError):
    """Something the user has to know before any folder is renamed."""


@dataclass
class RenameOptions:
    style: str = STYLE_NUMBER_NAME
    start: int = 1
    step: int = 1
    digits: int = 2                 # 0 = as many as the number needs
    separator: str = " - "
    text: str = ""                  # used by STYLE_TEXT_NUMBER, and as a prefix otherwise
    order: str = ORDER_NAME
    descending: bool = False
    drop_old_number: bool = True    # "03 - Holiday" becomes "01 - Holiday", not "01 - 03 - Holiday"
    include_hidden: bool = False
    pattern: str = "{n} - {name}"   # used by STYLE_CUSTOM
    kind: str = KIND_FOLDERS        # or KIND_FILES
    lower_extension: bool = False   # files: ".JPG" becomes ".jpg"
    extensions: str = ""            # files: only these, e.g. "jpg, png" (empty = every file)

    def validate(self) -> Optional[str]:
        if self.style not in {value for _label, value in STYLES}:
            return "Choose how the new names are built."
        if self.step == 0:
            return "The step between two numbers cannot be zero."
        if self.style == STYLE_TEXT_NUMBER and not self.text.strip():
            return "Type the text that goes before the number."
        if self.style == STYLE_CUSTOM:
            problem = check_pattern(self.pattern)
            if problem:
                return problem
        if re.search(r'[<>:"/\\|?*]', self.separator + self.text):
            return 'The text and the separator cannot contain  < > : " / \\ | ? *'
        return None


@dataclass
class Rename:
    """One folder and the name it will get."""

    source: Path
    new_name: str
    problem: str = ""

    @property
    def target(self) -> Path:
        return self.source.with_name(self.new_name)

    @property
    def changes(self) -> bool:
        return self.source.name != self.new_name

    @property
    def ok(self) -> bool:
        return not self.problem


@dataclass
class Journal:
    """What one run renamed, so it can be undone."""

    parent: str
    when: str
    moves: List[List[str]] = field(default_factory=list)   # [old full path, new full path]


# ----------------------------------------------------------------- listing
def natural_key(text: str):
    """Sort "2" before "10", and ignore upper/lower case."""
    return [int(part) if part.isdigit() else part.casefold() for part in _NATURAL_SPLIT.split(text)]


def _created(path: Path) -> float:
    stat = path.stat()
    return getattr(stat, "st_birthtime", None) or stat.st_ctime


def extension_filter(text: str) -> List[str]:
    """``"jpg, .PNG pdf"`` -> ``[".jpg", ".png", ".pdf"]``."""
    return [("." + part.lstrip(".")).lower() for part in re.split(r"[\s,;]+", text or "") if part.strip(".")]


def list_files(parent: Path, order: str = ORDER_NAME, descending: bool = False,
               include_hidden: bool = False, extensions: Sequence[str] = ()) -> List[Path]:
    """The files directly inside ``parent`` (only ``extensions`` when given), in order."""
    parent = Path(parent)
    if not parent.is_dir():
        raise RenameError(f"This folder does not exist: {parent}")
    try:
        files = [p for p in parent.iterdir() if p.is_file()]
    except OSError as exc:
        raise RenameError(f"The folder cannot be read: {exc}") from exc
    if not include_hidden:
        files = [p for p in files if not p.name.startswith(".") and not _is_hidden(p)]
    wanted = tuple(e.lower() for e in extensions)
    if wanted:
        files = [p for p in files if p.suffix.lower() in wanted]
    return sort_folders(files, order, descending)


def list_entries(parent: Path, options: "RenameOptions") -> List[Path]:
    """Folders or files, as ``options.kind`` says."""
    if options.kind == KIND_FILES:
        return list_files(parent, options.order, options.descending, options.include_hidden,
                          extension_filter(options.extensions))
    return list_folders(parent, options.order, options.descending, options.include_hidden)


def list_folders(parent: Path, order: str = ORDER_NAME, descending: bool = False,
                 include_hidden: bool = False) -> List[Path]:
    """The folders directly inside ``parent``, in the order asked for."""
    parent = Path(parent)
    if not parent.is_dir():
        raise RenameError(f"This folder does not exist: {parent}")
    try:
        folders = [p for p in parent.iterdir() if p.is_dir()]
    except OSError as exc:
        raise RenameError(f"The folder cannot be read: {exc}") from exc
    if not include_hidden:
        folders = [p for p in folders if not p.name.startswith(".") and not _is_hidden(p)]
    return sort_folders(folders, order, descending)


def sort_folders(folders: Iterable[Path], order: str, descending: bool = False) -> List[Path]:
    folders = list(folders)
    if order == ORDER_MANUAL:
        return list(reversed(folders)) if descending else folders
    if order == ORDER_MODIFIED:
        key = lambda p: (p.stat().st_mtime, natural_key(p.name))  # noqa: E731
    elif order == ORDER_CREATED:
        key = lambda p: (_created(p), natural_key(p.name))  # noqa: E731
    elif order == ORDER_TAKEN:
        def key(p):
            taken = file_facts(p)[0] if p.is_file() else None
            return (taken.timestamp() if taken else p.stat().st_mtime, natural_key(p.name))
    else:
        key = lambda p: natural_key(p.name)  # noqa: E731
    return sorted(folders, key=key, reverse=descending)


def _is_hidden(path: Path) -> bool:
    attributes = getattr(path.stat(), "st_file_attributes", 0)
    return bool(attributes & 0x2)  # FILE_ATTRIBUTE_HIDDEN on Windows


# ---------------------------------------------------------------- planning
def number_text(value: int, digits: int) -> str:
    sign = "-" if value < 0 else ""
    return sign + str(abs(value)).zfill(max(0, int(digits)))


def auto_digits(count: int, options: RenameOptions) -> int:
    """Enough digits for the last number, when the user asked for "auto"."""
    last = options.start + options.step * max(0, count - 1)
    return max(len(str(abs(options.start))), len(str(abs(last))))


def new_name_for(old_name: str, number: str, options: RenameOptions) -> str:
    base = old_name
    if options.drop_old_number:
        stripped = _LEADING_NUMBER.sub("", base)
        base = stripped or base
    text = options.text.strip()
    sep = options.separator
    if options.style == STYLE_NUMBER_ONLY:
        name = f"{text}{sep}{number}" if text else number
    elif options.style == STYLE_TEXT_NUMBER:
        name = f"{text} {number}"
    elif options.style == STYLE_NAME_NUMBER:
        name = f"{base}{sep}{number}"
        if text:
            name = f"{text}{sep}{name}"
    else:
        name = f"{number}{sep}{base}"
        if text:
            name = f"{text}{sep}{name}"
    return safe_filename(name, fallback=number)


# ------------------------------------------------------------ custom code
def check_pattern(pattern: str) -> Optional[str]:
    """Say what is wrong with a custom code, or None when it is usable."""
    if not pattern.strip():
        return "Type your code, for example  {n} - {name}"
    unknown = sorted({m.group(1) for m in _PIECE.finditer(pattern)} - _KNOWN_PIECES)
    if unknown:
        return "Unknown piece in the code: " + ", ".join("{%s}" % u for u in unknown)
    for match in _PIECE.finditer(pattern):
        key, modifier = match.group(1), match.group(2)
        if key == "n" and modifier and not modifier.isdigit():
            return "{n:...} takes a number of digits, for example {n:3}"
    if re.search(r'[<>:"/\\|?*]', _PIECE.sub("", pattern)):
        return 'The code cannot contain  < > : " / \\ | ? *'
    if not _PIECE.search(pattern):
        return "The code needs at least one piece such as {n}, or everything would get the same name."
    return None


def letters(value: int, lower: bool = False) -> str:
    """1 -> A, 26 -> Z, 27 -> AA, like spreadsheet columns."""
    if value < 1:
        return str(value)
    text = ""
    while value:
        value, rest = divmod(value - 1, 26)
        text = chr(65 + rest) + text
    return text.lower() if lower else text


def roman(value: int, lower: bool = False) -> str:
    if not 0 < value < 4000:
        return str(value)
    parts = ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
             (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    text = ""
    for amount, letter in parts:
        count, value = divmod(value, amount)
        text += letter * count
    return text.lower() if lower else text


def _changed(folder: Path) -> datetime:
    try:
        return datetime.fromtimestamp(folder.stat().st_mtime)
    except OSError:
        return datetime.now()


def _date_text(when: datetime, modifier: str) -> str:
    if "%" in modifier:
        try:
            return when.strftime(modifier)
        except ValueError:
            return when.strftime("%Y-%m-%d")
    return when.strftime("%Y-%m-%d %H.%M.%S" if modifier == "time" else "%Y-%m-%d")


@functools.lru_cache(maxsize=4096)
def _picture_facts(path: str, stamp: float):
    """Date taken and size of a picture, read once per version of the file."""
    from promak.core.imaging import RASTER_EXTENSIONS, photo_facts

    if Path(path).suffix.lower() not in RASTER_EXTENSIONS + (".heic", ".heif"):
        return None, 0, 0
    return photo_facts(Path(path))


def file_facts(path: Path):
    """``(date taken or None, width, height)`` for a picture; ``(None, 0, 0)`` otherwise."""
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return None, 0, 0
    return _picture_facts(str(path), stamp)


def _own_name(entry: Path, options: RenameOptions) -> str:
    """The part of the name a code works on: a file's name without its extension."""
    return entry.stem if options.kind == KIND_FILES else entry.name


def _extension(entry: Path, options: RenameOptions) -> str:
    if options.kind != KIND_FILES:
        return ""
    return entry.suffix.lower() if options.lower_extension else entry.suffix


def name_from_pattern(folder: Path, value: int, digits: int, total: int, options: RenameOptions) -> str:
    """Fill the custom code for one folder (or one file, without its extension)."""
    own = _own_name(folder, options)
    base = own
    if options.drop_old_number:
        base = _LEADING_NUMBER.sub("", base) or base
    when = _changed(folder)
    facts = file_facts(folder) if options.kind == KIND_FILES and re.search(r"\{(taken|width|height)", options.pattern) \
        else (None, 0, 0)

    def fill(match) -> str:
        key, modifier = match.group(1), (match.group(2) or "").strip()
        if "%" not in modifier:
            modifier = modifier.lower()
        if key == "n":
            return number_text(value, int(modifier) if modifier.isdigit() else digits)
        if key in ("name", "original"):
            text = base if key == "name" else own
            return {"upper": text.upper(), "lower": text.lower(), "title": text.title()}.get(modifier, text)
        if key == "letter":
            return letters(value, modifier == "lower")
        if key == "roman":
            return roman(value, modifier == "lower")
        if key == "date":
            return _date_text(when, modifier)
        if key == "taken":
            return _date_text(facts[0] or when, (match.group(2) or "").strip())
        if key == "ext":
            return folder.suffix.lstrip(".").lower() if options.kind == KIND_FILES else ""
        if key in ("width", "height"):
            size = facts[1] if key == "width" else facts[2]
            return str(size) if size else ""
        if key in ("year", "month", "day"):
            return when.strftime({"year": "%Y", "month": "%m", "day": "%d"}[key])
        if key == "today":
            return datetime.now().strftime("%Y-%m-%d")
        if key == "parent":
            return folder.parent.name
        if key == "total":
            return str(total)
        return match.group(0)

    return safe_filename(_PIECE.sub(fill, options.pattern), fallback=number_text(value, digits))


def plan_renames(folders: Sequence[Path], options: RenameOptions) -> List[Rename]:
    """Work out every new name; problems are attached, nothing is renamed."""
    folders = [Path(p) for p in folders]
    digits = options.digits or auto_digits(len(folders), options)
    plan: List[Rename] = []
    for index, folder in enumerate(folders):
        value = options.start + index * options.step
        if options.style == STYLE_CUSTOM:
            new_name = name_from_pattern(folder, value, digits, len(folders), options)
        else:
            new_name = new_name_for(_own_name(folder, options), number_text(value, digits), options)
        plan.append(Rename(folder, new_name + _extension(folder, options)))

    # two folders must not end up with the same name (Windows ignores case)
    seen = {}
    for item in plan:
        key = (str(item.source.parent).casefold(), item.new_name.casefold())
        if key in seen:
            item.problem = f"Same new name as '{seen[key].source.name}'"
            seen[key].problem = seen[key].problem or f"Same new name as '{item.source.name}'"
        else:
            seen[key] = item

    # nor take the name of something that is not being renamed
    moving = {str(item.source).casefold() for item in plan}
    for item in plan:
        if item.problem or not item.changes:
            continue
        target = item.target
        if target.exists() and str(target).casefold() not in moving and not _same_entry(target, item.source):
            item.problem = "A file or folder with this name is already there"
    return plan


def _same_entry(a: Path, b: Path) -> bool:
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


# ---------------------------------------------------------------- applying
def apply_renames(plan: Sequence[Rename], journal_dir: Optional[Path] = None,
                  journal_name: str = "renamer-last.json") -> Journal:
    """Rename every folder of the plan that has no problem and really changes.

    First every folder gets a temporary name, then its final one, so names
    can be swapped.  If anything goes wrong half-way, what was already done
    is put back, and the error is raised.
    """
    todo = [item for item in plan if item.ok and item.changes]
    if not todo:
        raise RenameError("There is nothing to rename.")
    parent = str(todo[0].source.parent)
    journal = Journal(parent=parent, when=datetime.now().isoformat(timespec="seconds"))
    tag = uuid.uuid4().hex[:8]
    staged: List[tuple] = []   # (original, temporary)
    finished: List[tuple] = []  # (temporary, final)
    try:
        for index, item in enumerate(todo):
            temporary = item.source.with_name(f".promak-{tag}-{index}")
            os.rename(item.source, temporary)
            staged.append((item.source, temporary))
        for (original, temporary), item in zip(staged, todo):
            if item.target.exists():
                raise RenameError(f"'{item.new_name}' appeared while renaming; nothing was changed.")
            os.rename(temporary, item.target)
            finished.append((temporary, item.target))
            journal.moves.append([str(original), str(item.target)])
    except Exception as exc:
        _roll_back(staged, finished)
        if isinstance(exc, RenameError):
            raise
        raise RenameError(_explain(exc)) from exc
    _save_journal(journal, journal_dir, journal_name)
    log.info("Renamed %d item(s) in %s", len(journal.moves), parent)
    return journal


def _roll_back(staged, finished) -> None:
    final_of = {str(temp): final for temp, final in finished}
    for original, temporary in reversed(staged):
        current = final_of.get(str(temporary), temporary)
        try:
            os.rename(current, original)
        except OSError:  # pragma: no cover - best effort
            log.exception("Could not put back %s", original)


def _explain(exc: Exception) -> str:
    if isinstance(exc, PermissionError):
        return (
            "Windows refused to rename. The file (or a file inside the folder) is probably "
            "open in another program, or the folder is open in Explorer: close it and retry. "
            "Nothing was changed."
        )
    return f"The folders could not be renamed ({exc}). Nothing was changed."


# ------------------------------------------------------------------- undo
def _journal_file(journal_dir: Optional[Path], name: str = "renamer-last.json") -> Path:
    folder = Path(journal_dir) if journal_dir else app_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / name


def _save_journal(journal: Journal, journal_dir: Optional[Path], name: str = "renamer-last.json") -> None:
    try:
        _journal_file(journal_dir, name).write_text(
            json.dumps(journal.__dict__, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:  # pragma: no cover - undo is a bonus, not a requirement
        log.warning("Could not write the undo journal", exc_info=True)


def last_journal(journal_dir: Optional[Path] = None, name: str = "renamer-last.json") -> Optional[Journal]:
    path = _journal_file(journal_dir, name)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Journal(parent=data["parent"], when=data["when"], moves=list(data["moves"]))
    except (OSError, ValueError, KeyError):
        return None


def undo_renames(journal: Journal, journal_dir: Optional[Path] = None, name: str = "renamer-last.json") -> int:
    """Put back the old names of the last run; returns how many were restored."""
    restored = 0
    problems = []
    staged = []
    tag = uuid.uuid4().hex[:8]
    for index, (old, new) in enumerate(journal.moves):
        new_path = Path(new)
        if not new_path.exists():
            problems.append(f"'{new_path.name}' is no longer there")
            continue
        temporary = new_path.with_name(f".promak-undo-{tag}-{index}")
        os.rename(new_path, temporary)
        staged.append((temporary, Path(old)))
    for temporary, old_path in staged:
        if old_path.exists():
            os.rename(temporary, temporary.with_name(temporary.name.replace(".promak-undo", "restored")))
            problems.append(f"'{old_path.name}' exists again, so it was not put back")
            continue
        os.rename(temporary, old_path)
        restored += 1
    try:
        _journal_file(journal_dir, name).unlink()
    except OSError:
        pass
    if problems:
        log.warning("Undo incomplete: %s", "; ".join(problems))
        raise RenameError(f"{restored} name(s) were put back. " + "; ".join(problems) + ".")
    return restored
