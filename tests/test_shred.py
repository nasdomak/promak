"""Secure delete, on throw-away files only."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from promak.tools.shred import engine as e


def test_wipe_overwrites_then_deletes(tmp_path, monkeypatch):
    target = tmp_path / "secret.txt"
    target.write_bytes(b"TOP SECRET" * 1000)
    written = []
    real_open = open

    def spy(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        if "+" in mode:
            original = handle.write

            def write(data):
                written.append(bytes(data))
                return original(data)

            handle.write = write
        return handle

    monkeypatch.setattr("builtins.open", spy)
    e.wipe_file(target, passes=3)
    assert not target.exists()
    assert sum(len(block) for block in written) == 3 * 10_000
    assert all(b"TOP SECRET" not in block for block in written)
    assert list(tmp_path.iterdir()) == []


def test_folders_read_only_files_and_links(tmp_path):
    folder = tmp_path / "old"
    (folder / "deep").mkdir(parents=True)
    (folder / "a.txt").write_text("a")
    locked = folder / "deep" / "b.txt"
    locked.write_text("b")
    os.chmod(locked, 0o444)
    outside = tmp_path / "keep.txt"
    outside.write_text("keep")
    try:
        (folder / "link").symlink_to(outside)
    except (OSError, NotImplementedError):
        pass
    files, _folders = e.collect([folder])
    result = e.shred(e.ShredOptions(items=[folder]))
    assert result["failed"] == 0 and result["done"] == len(files)
    assert not folder.exists()
    assert outside.read_text() == "keep"     # a link's target is never touched


def test_dangerous_targets_are_refused(tmp_path):
    assert "whole drive" in e.forbidden(Path(Path.cwd().anchor))
    assert e.forbidden(Path.home())
    assert e.forbidden(tmp_path / "missing")
    assert e.forbidden(tmp_path) == ""
    assert e.ShredOptions().validate()


def test_cli_needs_yes(tmp_path):
    from promak import cli

    target = tmp_path / "x.bin"
    target.write_bytes(b"1234")
    assert cli.main(["shred", str(target)]) == 0
    assert target.exists()
    assert cli.main(["shred", str(target), "--yes"]) == 0
    assert not target.exists()


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_shred_screen_asks_for_the_word(qapp, tmp_path, monkeypatch):
    from promak.tools.shred import panel as module

    target = tmp_path / "old.txt"
    target.write_text("old")
    panel = module.ShredPanel()
    try:
        assert not panel.notice.isHidden() and "SSD" in panel.notice.text()
        panel.add_items([target, Path.home()])
        assert panel.items.count() == 1          # the home folder was refused
        panel.on_scanned(panel.run_now(panel.scan_task()))
        assert panel.can_apply()
        monkeypatch.setattr(module.QMessageBox, "question", staticmethod(lambda *a, **k: module.QMessageBox.Yes))
        monkeypatch.setattr(module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("delete", True)))
        assert not panel.confirm_apply()           # the word must be typed exactly
        monkeypatch.setattr(module.QInputDialog, "getText", staticmethod(lambda *a, **k: ("DELETE", True)))
        assert panel.confirm_apply()
        panel.run_now(panel.apply_task())
        assert not target.exists()
    finally:
        panel.deleteLater()
        qapp.processEvents()
