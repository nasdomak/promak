"""The duplicate finder, on tiny files made on the spot."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from promak.core.fileops import load_journal, undo_journal
from promak.tools.duplicates import engine as e


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _picture(path: Path, size=(400, 300), quality=90) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (400, 300), (30, 90, 200))
    draw = ImageDraw.Draw(image)
    draw.ellipse((80, 40, 300, 260), fill=(250, 220, 60))
    draw.rectangle((10, 200, 120, 290), fill=(20, 20, 20))
    image.resize(size).save(path, quality=quality)
    return path


def test_exact_duplicates_are_grouped_and_one_is_kept(tmp_path):
    data = os.urandom(200_000)
    a = _write(tmp_path / "a" / "report.pdf", data)
    b = _write(tmp_path / "b" / "report copy.pdf", data)
    _write(tmp_path / "b" / "other.pdf", os.urandom(200_000))  # same size, other bytes
    os.utime(a, (1_000_000, 1_000_000))
    options = e.DuplicateOptions(folders=[tmp_path], keep=e.KEEP_OLDEST)
    groups = e.find_duplicates(options)
    assert len(groups) == 1
    group = groups[0]
    assert {entry.path for entry in group.entries} == {a, b}
    assert group.keeper.path == a
    assert group.freed_bytes == 200_000


def test_small_files_and_subfolders_options(tmp_path):
    _write(tmp_path / "x.txt", b"same")
    _write(tmp_path / "y.txt", b"same")
    _write(tmp_path / "deep" / "z.txt", b"same")
    assert e.find_duplicates(e.DuplicateOptions(folders=[tmp_path], min_kb=1)) == []
    groups = e.find_duplicates(e.DuplicateOptions(folders=[tmp_path], min_kb=0, recursive=False))
    assert len(groups) == 1 and len(groups[0].entries) == 2
    groups = e.find_duplicates(e.DuplicateOptions(folders=[tmp_path], min_kb=0))
    assert len(groups[0].entries) == 3


def test_similar_pictures(tmp_path):
    big = _picture(tmp_path / "beach.jpg", (800, 600), 95)
    small = _picture(tmp_path / "beach-small.jpg", (200, 150), 60)
    other = tmp_path / "forest.jpg"
    Image.effect_noise((400, 300), 80).convert("RGB").save(other)
    groups = e.find_duplicates(e.DuplicateOptions(folders=[tmp_path], mode=e.SIMILAR, similarity=90))
    assert len(groups) == 1
    assert {entry.path for entry in groups[0].entries} == {big, small}
    # the largest picture is the one kept
    assert groups[0].keeper.path == big


def test_move_and_undo(tmp_path):
    data = os.urandom(5000)
    a = _write(tmp_path / "photos" / "a.bin", data)
    b = _write(tmp_path / "photos" / "sub" / "b.bin", data)
    target = tmp_path / "removed"
    options = e.DuplicateOptions(folders=[tmp_path / "photos"], keep=e.KEEP_SHORTEST, action=e.TO_FOLDER,
                                 move_to=target)
    groups = e.find_duplicates(options)
    result = e.remove_duplicates(groups, options, journal_dir=tmp_path / "journal")
    assert result["done"] == 1
    assert a.exists() and not b.exists()
    assert (target / "sub" / "b.bin").read_bytes() == data
    journal = load_journal(e.TOOL, tmp_path / "journal")
    assert undo_journal(journal) == 1
    assert b.read_bytes() == data


def test_recycle_bin_is_used(tmp_path, monkeypatch):
    import promak.core.fileops as fileops

    binned = []
    monkeypatch.setattr(fileops, "to_recycle_bin", lambda path: binned.append(path))
    monkeypatch.setattr(e, "to_recycle_bin", lambda path: binned.append(path))
    data = os.urandom(3000)
    _write(tmp_path / "a.bin", data)
    _write(tmp_path / "b.bin", data)
    options = e.DuplicateOptions(folders=[tmp_path])
    groups = e.find_duplicates(options)
    e.remove_duplicates(groups, options)
    assert len(binned) == 1


def test_a_group_with_nothing_kept_is_refused(tmp_path):
    data = os.urandom(3000)
    _write(tmp_path / "a.bin", data)
    _write(tmp_path / "b.bin", data)
    options = e.DuplicateOptions(folders=[tmp_path], action=e.TO_FOLDER, move_to=tmp_path / "out")
    groups = e.find_duplicates(options)
    for entry in groups[0].entries:
        entry.remove = True
    with pytest.raises(e.FileOpError, match="keep at least one"):
        e.remove_duplicates(groups, options)
    assert e.DuplicateOptions(folders=[tmp_path], action=e.TO_FOLDER, move_to=tmp_path).validate_action()


def test_cli_preview_and_move(tmp_path, monkeypatch, capsys):
    from promak import cli

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    data = os.urandom(4000)
    _write(tmp_path / "in" / "a.bin", data)
    _write(tmp_path / "in" / "b.bin", data)
    assert cli.main(["duplicates", str(tmp_path / "in")]) == 0
    assert "Preview only" in capsys.readouterr().out
    assert cli.main(["duplicates", str(tmp_path / "in"), "--move-to", str(tmp_path / "out"), "--yes"]) == 0
    assert len(list((tmp_path / "in").iterdir())) == 1


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_duplicates_screen(qapp, tmp_path):
    from PySide6.QtCore import Qt

    from promak.tools.duplicates.panel import DuplicatesPanel

    data = os.urandom(6000)
    _write(tmp_path / "in" / "a.bin", data)
    _write(tmp_path / "in" / "b.bin", data)
    panel = DuplicatesPanel()
    try:
        panel.folders.set_folders([tmp_path / "in"])
        panel.on_scanned(panel.run_now(panel.scan_task()))
        assert panel.tree.topLevelItemCount() == 1
        group = panel.tree.topLevelItem(0)
        assert group.childCount() == 2
        ticked = [group.child(i).checkState(0) == Qt.Checked for i in range(2)]
        assert ticked.count(True) == 1
        assert panel.can_apply()
        assert "1 file(s)" in panel.apply_button.text()
        # unticking keeps both: nothing left to do
        for i in range(2):
            group.child(i).setCheckState(0, Qt.Unchecked)
        assert not panel.can_apply()
    finally:
        panel.deleteLater()
        qapp.processEvents()
