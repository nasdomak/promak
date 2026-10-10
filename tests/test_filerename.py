"""The batch file renamer: the folder renamer's engine working on files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from promak.tools.filerename import engine as e
from promak.tools.renamer.engine import check_pattern


def _photo(path: Path, taken: str = "", size=(64, 48)) -> Path:
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
    Image.new("RGB", size, "blue").save(path, exif=exif)
    return path


def test_files_keep_their_extension_and_get_the_new_pieces(tmp_path):
    _photo(tmp_path / "IMG_10.JPG", "2025:08:01 09:30:00", (80, 60))
    _photo(tmp_path / "IMG_9.JPG", "2025:07:31 18:00:00", (60, 80))
    (tmp_path / "notes.txt").write_text("hello")
    (tmp_path / "Album").mkdir()  # folders are left alone
    options = e.file_options(pattern="{taken} {n:2} {width}x{height} {ext}", lower_extension=True)
    files = e.list_files(tmp_path)
    assert [p.name for p in files] == ["IMG_9.JPG", "IMG_10.JPG", "notes.txt"]
    plan = e.plan_renames(files, options)
    names = [item.new_name for item in plan]
    assert names[0] == "2025-07-31 01 60x80 jpg.jpg"
    assert names[1] == "2025-08-01 02 80x60 jpg.jpg"
    # a text file has no date taken (the date changed is used) and no size
    assert names[2].endswith(" 03 x txt.txt")


def test_only_some_extensions_and_date_formats(tmp_path):
    _photo(tmp_path / "a.jpg", "2024:01:02 03:04:05")
    (tmp_path / "b.pdf").write_bytes(b"%PDF-1.4")
    assert e.extension_filter("PNG, .jpg pdf") == [".png", ".jpg", ".pdf"]
    files = e.list_files(tmp_path, extensions=e.extension_filter("jpg"))
    assert [p.name for p in files] == ["a.jpg"]
    options = e.file_options(pattern="{taken:%Y%m%d}_{name}")
    assert e.plan_renames(files, options)[0].new_name == "20240102_a.jpg"
    options = e.file_options(pattern="{taken:time}")
    assert e.plan_renames(files, options)[0].new_name == "2024-01-02 03.04.05.jpg"
    assert check_pattern("{taken} {width}") is None


def test_order_by_date_taken(tmp_path):
    from promak.tools.renamer.engine import ORDER_TAKEN

    _photo(tmp_path / "a.jpg", "2026:05:01 10:00:00")
    _photo(tmp_path / "b.jpg", "2020:05:01 10:00:00")
    assert [p.name for p in e.list_files(tmp_path, order=ORDER_TAKEN)] == ["b.jpg", "a.jpg"]


def test_rename_files_and_undo(tmp_path):
    for name in ("b.txt", "a.txt", "c.TXT"):
        (tmp_path / name).write_text(name)
    journal_dir = tmp_path / "journal"
    options = e.file_options(pattern="Note {n}", digits=0, lower_extension=True)
    plan = e.plan_renames(e.list_files(tmp_path), options)
    journal = e.apply_renames(plan, journal_dir=journal_dir, journal_name=e.JOURNAL)
    assert len(journal.moves) == 3
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["Note 1.txt", "Note 2.txt", "Note 3.txt"]
    assert (tmp_path / "Note 1.txt").read_text() == "a.txt"
    restored = e.undo_renames(e.last_journal(journal_dir, e.JOURNAL), journal_dir, e.JOURNAL)
    assert restored == 3
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["a.txt", "b.txt", "c.TXT"]
    # the folder renamer keeps its own journal
    assert e.last_journal(journal_dir) is None


def test_files_can_swap_names(tmp_path):
    (tmp_path / "1.txt").write_text("one")
    (tmp_path / "2.txt").write_text("two")
    options = e.file_options(pattern="{n}", digits=0, descending=True)
    plan = e.plan_renames(e.list_files(tmp_path, descending=True), options)
    assert [(i.source.name, i.new_name) for i in plan] == [("2.txt", "1.txt"), ("1.txt", "2.txt")]
    assert all(item.ok for item in plan)
    e.apply_renames(plan, journal_dir=tmp_path / "j", journal_name=e.JOURNAL)
    assert (tmp_path / "1.txt").read_text() == "two"


def test_clashes_are_reported(tmp_path):
    (tmp_path / "a.txt").write_text("a")
    (tmp_path / "b.txt").write_text("b")
    options = e.file_options(pattern="same {ext}")
    plan = e.plan_renames(e.list_files(tmp_path), options)
    assert all(item.problem for item in plan)


def test_cli_rename_files(tmp_path, monkeypatch):
    from promak import cli

    for name in ("x.txt", "y.txt"):
        (tmp_path / name).write_text(name)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    assert cli.main(["rename", str(tmp_path), "--files", "--code", "doc-{n}", "--yes"]) == 0
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["doc-01.txt", "doc-02.txt"]
    assert cli.main(["rename", "--files", "--undo"]) == 0
    assert sorted(p.name for p in tmp_path.iterdir() if p.is_file()) == ["x.txt", "y.txt"]


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_file_renamer_screen(qapp, tmp_path, monkeypatch):
    from promak.tools.filerename import panel as module

    from promak.tools.renamer import panel as renamer_module

    monkeypatch.setattr(renamer_module.QMessageBox, "question",
                        staticmethod(lambda *a, **k: renamer_module.QMessageBox.Yes))
    folder = tmp_path / "photos"
    folder.mkdir()
    _photo(folder / "IMG_1.JPG", "2026:07:12 10:00:00")
    _photo(folder / "IMG_2.JPG", "2026:07:13 10:00:00")
    page = module.FileRenamerPanel()
    try:
        page.pattern_input.setText("Trip {taken} {n:3}")
        page.lower_ext_check.setChecked(True)
        page.set_folder(folder)
        assert page.table.rowCount() == 2
        assert page.table.item(0, 1).text() == "Trip 2026-07-12 001.jpg"
        assert "2 file(s)" in page.start_button.text()
        page._apply()
        assert sorted(p.name for p in folder.iterdir()) == ["Trip 2026-07-12 001.jpg", "Trip 2026-07-13 002.jpg"]
        page._undo()
        assert sorted(p.name for p in folder.iterdir()) == ["IMG_1.JPG", "IMG_2.JPG"]
    finally:
        page.deleteLater()
        qapp.processEvents()
