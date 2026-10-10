"""The watched folder."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from promak.tools.recipes.engine import Recipe, step_from_options
from promak.tools.text.engine import TextOptions
from promak.tools.watch import engine as e


def _recipe():
    return Recipe("Clean text", [step_from_options("text", TextOptions(make="clean", output_format="md"))])


def test_new_files_are_taken_once_finished(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "old.txt").write_text("already here")
    watcher = e.FolderWatcher(e.WatchOptions(folder=folder, output=tmp_path / "out"), (".txt",))
    assert watcher.poll() == []
    (folder / "new.txt").write_text("hello")
    (folder / "photo.jpg").write_bytes(b"x")              # not a kind the recipe opens
    (folder / "loading.txt.part").write_text("half")      # still downloading
    assert watcher.poll() == []                          # seen once: maybe still growing
    assert watcher.poll() == [folder / "new.txt"]
    assert watcher.poll() == []                          # done once only
    time.sleep(0.05)
    (folder / "new.txt").write_text("hello again, longer")
    watcher.poll()
    assert watcher.poll() == [folder / "new.txt"]         # new content: done again


def test_existing_files_on_request_and_bad_options(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "old.txt").write_text("x")
    watcher = e.FolderWatcher(e.WatchOptions(folder=folder, output=tmp_path / "o", include_existing=True))
    watcher.poll()
    assert watcher.poll() == [folder / "old.txt"]
    assert e.WatchOptions(folder=folder, output=folder).validate()
    assert e.WatchOptions(folder=folder, output=folder / "out", recursive=True).validate()
    assert e.WatchOptions(folder=tmp_path / "nope", output=tmp_path).validate()


def test_process_one_file(tmp_path):
    source = tmp_path / "note.txt"
    source.write_text("Hello   world", encoding="utf-8")
    job = e.process(source, _recipe(), tmp_path / "out")
    assert job.output and job.output.suffix == ".md", job.error
    assert source.read_text(encoding="utf-8") == "Hello   world"


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_watch_screen(qapp, tmp_path):
    from promak.tools.recipes.engine import save_recipe
    from promak.tools.watch.panel import WatchPanel

    save_recipe(_recipe())
    folder, output = tmp_path / "in", tmp_path / "out"
    folder.mkdir()
    panel = WatchPanel()
    try:
        panel._fill_actions()
        panel.action_combo.setCurrentIndex(panel.action_combo.findData("recipe:Clean text"))
        panel.folder_input.setText(str(folder))
        panel.output_input.setText(str(output))
        panel.apply()
        assert panel.watcher is not None and panel.apply_button.text() == "Stop watching"
        (folder / "a.txt").write_text("one", encoding="utf-8")
        panel.poll()
        panel.poll()
        assert panel._task is not None
        panel._task.wait(20000)
        qapp.processEvents()
        assert panel.table.rowCount() == 1
        assert list(output.glob("*.md"))
        panel.stop()
        assert panel.watcher is None
    finally:
        panel.deleteLater()
        qapp.processEvents()


def test_cli_rejects_unknown_recipe(tmp_path, monkeypatch):
    from promak import cli

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    assert cli.main(["watch", str(tmp_path), "--recipe", "nope", "--out", str(tmp_path / "o")]) == 2


def test_watch_forever_stops(tmp_path):
    folder = tmp_path / "in"
    folder.mkdir()
    (folder / "x.txt").write_text("text", encoding="utf-8")
    looks = []
    count = e.watch_forever(e.WatchOptions(folder=folder, output=tmp_path / "o", include_existing=True), _recipe(),
                            interval=0.01, stop=lambda: looks.append(1) or len(looks) > 3)
    assert count == 1 and list((tmp_path / "o").glob("*.md"))
    assert Path(folder / "x.txt").exists()
