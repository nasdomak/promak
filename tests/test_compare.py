"""Comparing two folders and copying the missing files."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from promak.core.fileops import load_journal, undo_journal
from promak.tools.compare import engine as e


def _folders(tmp_path: Path):
    left, right = tmp_path / "left", tmp_path / "right"
    (left / "sub").mkdir(parents=True)
    right.mkdir()
    for name in ("same.txt", "sub/deep.txt"):
        (left / name).parent.mkdir(parents=True, exist_ok=True)
        (right / name).parent.mkdir(parents=True, exist_ok=True)
        (left / name).write_text("equal", encoding="utf-8")
        (right / name).write_text("equal", encoding="utf-8")
    (left / "changed.txt").write_text("aaaa", encoding="utf-8")
    (right / "changed.txt").write_text("bbbb", encoding="utf-8")   # same size, other content
    (left / "only-left.txt").write_text("L", encoding="utf-8")
    (right / "only-right.txt").write_text("R", encoding="utf-8")
    return left, right


def test_four_answers(tmp_path):
    left, right = _folders(tmp_path)
    results = e.compare_folders(e.CompareOptions(left=left, right=right))
    by_name = {item.relative: item.status for item in results}
    assert by_name == {"changed.txt": e.DIFFERENT, "only-left.txt": e.ONLY_LEFT, "only-right.txt": e.ONLY_RIGHT,
                       "same.txt": e.IDENTICAL, "sub/deep.txt": e.IDENTICAL}
    assert e.counts(results)[e.IDENTICAL] == 2
    # quick mode trusts size and date: the dates differ by less than 2 s here
    quick = {i.relative: i.status for i in e.compare_folders(e.CompareOptions(left=left, right=right, quick=True))}
    assert quick["changed.txt"] == e.IDENTICAL
    flat = {i.relative for i in e.compare_folders(e.CompareOptions(left=left, right=right, recursive=False))}
    assert "sub/deep.txt" not in flat


def test_copy_both_ways_and_undo(tmp_path):
    left, right = _folders(tmp_path)
    options = e.CompareOptions(left=left, right=right)
    results = e.compare_folders(options)
    result = e.copy_missing(results, options, e.BOTH_WAYS, journal_dir=tmp_path / "j")
    assert result["done"] == 2
    assert (right / "only-left.txt").read_text(encoding="utf-8") == "L"
    assert (left / "only-right.txt").read_text(encoding="utf-8") == "R"
    assert (right / "changed.txt").read_text(encoding="utf-8") == "bbbb"   # never overwritten
    again = e.counts(e.compare_folders(options))
    assert again[e.ONLY_LEFT] == again[e.ONLY_RIGHT] == 0
    assert undo_journal(load_journal(e.TOOL, tmp_path / "j")) == 2
    assert not (right / "only-left.txt").exists() and (left / "only-left.txt").exists()


def test_bad_folders():
    assert e.CompareOptions().validate()
    assert e.CompareOptions(left=Path("."), right=Path(".")).validate()


def test_nested_folders_are_refused(tmp_path):
    (tmp_path / "inner").mkdir()
    assert "inside" in e.CompareOptions(left=tmp_path, right=tmp_path / "inner").validate()


def test_cli(tmp_path, monkeypatch, capsys):
    from promak import cli

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    left, right = _folders(tmp_path)
    assert cli.main(["compare", str(left), str(right), "--copy", "left-to-right"]) == 0
    assert "would be copied" in capsys.readouterr().out
    assert cli.main(["compare", str(left), str(right), "--copy", "left-to-right", "--yes"]) == 0
    assert (right / "only-left.txt").exists()
    assert cli.main(["compare", "--undo"]) == 0
    assert not (right / "only-left.txt").exists()


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_compare_screen(qapp, tmp_path):
    from promak.tools.compare.panel import ComparePanel
    from promak.ui.plan_panel import select

    left, right = _folders(tmp_path)
    panel = ComparePanel()
    try:
        panel.on_dropped([left])
        panel.on_dropped([right])
        assert panel.left_input.text() == str(left) and panel.right_input.text() == str(right)
        panel.on_scanned(panel.run_now(panel.scan_task()))
        select(panel.show_combo, "diff")
        assert panel.table.rowCount() == 3
        select(panel.show_combo, "all")
        assert panel.table.rowCount() == 5
        assert "1 missing" in panel.apply_button.text()
    finally:
        panel.deleteLater()
        qapp.processEvents()
