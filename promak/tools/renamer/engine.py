"""Giving the folders inside a folder sequential names.

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
"""

from __future__ import annotations

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

ORDERS = [
    ("By name (2 before 10)", ORDER_NAME),
    ("By date changed, oldest first", ORDER_MODIFIED),
    ("By date created, oldest first", ORDER_CREATED),
    ("As I arrange them", ORDER_MANUAL),
]

STYLE_NUMBER_NAME = "number_name"
STYLE_NAME_NUMBER = "name_number"
STYLE_NUMBER_ONLY = "number_only"
STYLE_TEXT_NUMBER = "text_number"

STYLES = [
    ("Number, then the old name   (01 - Holiday)", STYLE_NUMBER_NAME),
    ("Old name, then the number   (Holiday - 01)", STYLE_NAME_NUMBER),
    ("Number only   (01)", STYLE_NUMBER_ONLY),
    ("My text and the number   (Project 01)", STYLE_TEXT_NUMBER),
]

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

    def validate(self) -> Optional[str]:
        if self.style not in {value for _label, value in STYLES}:
            return "Choose how the new names are built."
        if self.step == 0:
            return "The step between two numbers cannot be zero."
        if self.style == STYLE_TEXT_NUMBER and not self.text.strip():
            return "Type the text that goes before the number."
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


def plan_renames(folders: Sequence[Path], options: RenameOptions) -> List[Rename]:
    """Work out every new name; problems are attached, nothing is renamed."""
    folders = [Path(p) for p in folders]
    digits = options.digits or auto_digits(len(folders), options)
    plan: List[Rename] = []
    for index, folder in enumerate(folders):
        number = number_text(options.start + index * options.step, digits)
        plan.append(Rename(folder, new_name_for(folder.name, number, options)))

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
def apply_renames(plan: Sequence[Rename], journal_dir: Optional[Path] = None) -> Journal:
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
    _save_journal(journal, journal_dir)
    log.info("Renamed %d folder(s) in %s", len(journal.moves), parent)
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
            "Windows refused to rename a folder. A file inside it is probably open in "
            "another program (or the folder is open in Explorer): close it and retry. "
            "Nothing was changed."
        )
    return f"The folders could not be renamed ({exc}). Nothing was changed."


# ------------------------------------------------------------------- undo
def _journal_file(journal_dir: Optional[Path]) -> Path:
    folder = Path(journal_dir) if journal_dir else app_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "renamer-last.json"


def _save_journal(journal: Journal, journal_dir: Optional[Path]) -> None:
    try:
        _journal_file(journal_dir).write_text(
            json.dumps(journal.__dict__, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except OSError:  # pragma: no cover - undo is a bonus, not a requirement
        log.warning("Could not write the undo journal", exc_info=True)


def last_journal(journal_dir: Optional[Path] = None) -> Optional[Journal]:
    path = _journal_file(journal_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Journal(parent=data["parent"], when=data["when"], moves=list(data["moves"]))
    except (OSError, ValueError, KeyError):
        return None


def undo_renames(journal: Journal, journal_dir: Optional[Path] = None) -> int:
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
        _journal_file(journal_dir).unlink()
    except OSError:
        pass
    if problems:
        log.warning("Undo incomplete: %s", "; ".join(problems))
        raise RenameError(f"{restored} folder(s) were put back. " + "; ".join(problems) + ".")
    return restored
