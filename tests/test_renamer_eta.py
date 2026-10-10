"""The sequential folder renamer and the time-left estimate."""

from __future__ import annotations

import os

import pytest

from promak.core.eta import RemainingTime, describe_seconds
from promak.tools.renamer.engine import (
    ORDER_MODIFIED,
    STYLE_NAME_NUMBER,
    STYLE_NUMBER_ONLY,
    STYLE_TEXT_NUMBER,
    RenameError,
    RenameOptions,
    apply_renames,
    last_journal,
    list_folders,
    plan_renames,
    undo_renames,
)


# ---------------------------------------------------------------- time left
class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def test_no_estimate_too_early_then_a_sensible_one():
    clock = FakeClock()
    eta = RemainingTime(clock)
    eta.start()
    assert eta.seconds_left(0.5) is None          # no time has passed yet
    clock.now += 60
    assert eta.seconds_left(0.25) == pytest.approx(180)
    assert eta.seconds_left(1.0) == 0.0


def test_time_left_in_words():
    assert describe_seconds(None) == "estimating time left"
    assert describe_seconds(4) == "a few seconds left"
    assert describe_seconds(42) == "about 40 s left"
    assert describe_seconds(250) == "about 4 min left"
    assert describe_seconds(2 * 3600 + 300) == "about 2 h 05 min left"


# ------------------------------------------------------------------ renamer
def _make(tmp_path, *names):
    for name in names:
        (tmp_path / name).mkdir()
    (tmp_path / "a file.txt").write_text("not a folder")
    return tmp_path


def test_folders_are_listed_in_natural_order_without_files(tmp_path):
    _make(tmp_path, "trip 10", "trip 2", "Alpha")
    assert [p.name for p in list_folders(tmp_path)] == ["Alpha", "trip 2", "trip 10"]


def test_order_by_date_changed(tmp_path):
    _make(tmp_path, "b", "a")
    os.utime(tmp_path / "a", (2_000_000_000, 2_000_000_000))
    os.utime(tmp_path / "b", (1_000_000_000, 1_000_000_000))
    assert [p.name for p in list_folders(tmp_path, ORDER_MODIFIED)] == ["b", "a"]


def test_plan_styles(tmp_path):
    _make(tmp_path, "07 - Holiday", "Work")
    folders = list_folders(tmp_path)
    assert [r.new_name for r in plan_renames(folders, RenameOptions())] == ["01 - Holiday", "02 - Work"]
    keep = RenameOptions(drop_old_number=False, digits=3)
    assert plan_renames(folders, keep)[0].new_name == "001 - 07 - Holiday"
    after = RenameOptions(style=STYLE_NAME_NUMBER, start=5, step=5)
    assert [r.new_name for r in plan_renames(folders, after)] == ["Holiday - 05", "Work - 10"]
    only = RenameOptions(style=STYLE_NUMBER_ONLY, digits=0, start=9)
    assert [r.new_name for r in plan_renames(folders, only)] == ["09", "10"]
    text = RenameOptions(style=STYLE_TEXT_NUMBER, text="Project")
    assert plan_renames(folders, text)[1].new_name == "Project 02"
    assert RenameOptions(style=STYLE_TEXT_NUMBER).validate()
    assert RenameOptions(separator="/").validate()


def test_existing_name_not_in_the_list_is_a_problem(tmp_path):
    _make(tmp_path, "b")
    (tmp_path / "01 - b").write_text("a file with the wanted name")
    plan = plan_renames(list_folders(tmp_path), RenameOptions())
    assert plan[0].problem


def test_swapping_names_and_undo(tmp_path):
    _make(tmp_path, "02", "01")
    folders = list(reversed(list_folders(tmp_path)))       # 02 first, then 01
    (tmp_path / "02" / "inside.txt").write_text("kept")
    journal_dir = tmp_path.parent / (tmp_path.name + "-journal")
    plan = plan_renames(folders, RenameOptions(style=STYLE_NUMBER_ONLY))
    assert all(r.ok for r in plan)
    apply_renames(plan, journal_dir)
    assert (tmp_path / "01" / "inside.txt").read_text() == "kept"
    journal = last_journal(journal_dir)
    assert journal and len(journal.moves) == 2
    assert undo_renames(journal, journal_dir) == 2
    assert (tmp_path / "02" / "inside.txt").exists()
    assert last_journal(journal_dir) is None


def test_nothing_to_rename(tmp_path):
    _make(tmp_path, "01 - x")
    with pytest.raises(RenameError):
        apply_renames(plan_renames(list_folders(tmp_path), RenameOptions()), tmp_path / "j")


# -------------------------------------------------------------- custom code
def test_custom_code_pieces(tmp_path):
    from promak.tools.renamer.engine import STYLE_CUSTOM, check_pattern, letters, roman

    _make(tmp_path, "03 - Holiday", "work")
    os.utime(tmp_path / "work", (1_780_000_000, 1_780_000_000))
    folders = list_folders(tmp_path)

    def names(pattern, **extra):
        options = RenameOptions(style=STYLE_CUSTOM, pattern=pattern, **extra)
        assert options.validate() is None, options.validate()
        return [r.new_name for r in plan_renames(folders, options)]

    assert names("PRJ-{n:3} {name}") == ["PRJ-001 Holiday", "PRJ-002 work"]
    assert names("{letter}. {name:upper}") == ["A. HOLIDAY", "B. WORK"]
    assert names("Chapter {roman:lower} - {original}") == ["Chapter i - 03 - Holiday", "Chapter ii - work"]
    assert names("{parent} {n} of {total}")[1] == f"{tmp_path.name} 02 of 2"
    year = __import__("datetime").datetime.fromtimestamp(1_780_000_000).strftime("%Y")
    assert names("{year} {name}")[1] == f"{year} work"
    assert check_pattern("{n} {colour}") == "Unknown piece in the code: {colour}"
    assert check_pattern("fixed name")
    assert check_pattern("{n}/{name}")
    assert check_pattern("{n:x}")
    assert letters(27) == "AA" and roman(1994) == "MCMXCIV"
