"""Tests of the screens themselves, run without a visible window.

Qt is started in its "offscreen" mode, so these run on a server too.  They
are skipped when PySide6 is not installed.  Each test gets its own empty
settings folder, so running them never touches the settings of the person
using Promak on the same computer.

The scenario at the heart of this file is the one reported on 08/10/2026:
links added, then a different destination folder picked, then Start - and
the files ended up in the old folder.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


@pytest.fixture(autouse=True)
def private_settings(tmp_path, monkeypatch):
    """A settings folder of its own for every test."""
    data = tmp_path / "appdata"
    data.mkdir()
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(data))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    (tmp_path / "home").mkdir()
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    yield


class _FakeWorker:
    """Stands in for the background thread: it only remembers its jobs."""

    started_with = None

    def __init__(self, jobs, *_args, **_kwargs):
        type(self).started_with = list(jobs)
        self.job_updated = self.log_message = self.run_finished = _Signal()

    def start(self):
        pass

    def isRunning(self):  # noqa: N802 - Qt naming
        return False


class _Signal:
    def connect(self, *_args):
        pass


# ===================================================================== video
@pytest.fixture
def video_panel(qapp, monkeypatch):
    from promak.tools.video import panel as video_module

    monkeypatch.setattr(video_module, "PipelineWorker", _FakeWorker)
    monkeypatch.setattr(video_module, "missing_dependencies", lambda: [])
    monkeypatch.setattr(video_module, "check_dependencies", lambda: [])
    _FakeWorker.started_with = None
    panel = video_module.VideoPanel()
    yield panel
    panel.deleteLater()


def _add_links(panel, *urls):
    panel.url_input.setPlainText("\n".join(urls))
    panel._add_urls()


def test_video_folder_changed_after_adding_is_the_one_used(video_panel, tmp_path):
    old, new = tmp_path / "old", tmp_path / "new"
    video_panel.destination_input.setText(str(old))
    _add_links(video_panel, "https://a.example/v/1", "https://a.example/v/2")
    assert [job.destination for job in video_panel._jobs] == [old, old]

    # what "Browse..." does: the field changes after the links are queued
    video_panel.destination_input.setText(str(new))
    video_panel._start()

    started = _FakeWorker.started_with
    assert started is not None, "the run did not start"
    assert [job.destination for job in started] == [new, new]
    assert new.is_dir()
    # the queue shows the folder that will really be used
    assert video_panel.table.item(0, 1).text() == str(new)


def test_video_folder_typed_after_adding_is_the_one_used(video_panel, tmp_path):
    video_panel.destination_input.setText(str(tmp_path / "old"))
    _add_links(video_panel, "https://a.example/v/1")
    video_panel.destination_input.clear()
    video_panel.destination_input.insert(str(tmp_path / "typed"))
    video_panel._start()
    assert _FakeWorker.started_with[0].destination == tmp_path / "typed"


def test_video_change_folder_keeps_its_own_folder(video_panel, tmp_path, monkeypatch):
    from promak.tools.video import panel as video_module

    video_panel.destination_input.setText(str(tmp_path / "main"))
    _add_links(video_panel, "https://a.example/v/1", "https://a.example/v/2")
    video_panel.table.selectRow(0)
    special = tmp_path / "special"
    monkeypatch.setattr(
        video_module.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(special))
    )
    video_panel._change_folder_for_selection()

    video_panel.destination_input.setText(str(tmp_path / "main2"))
    video_panel._start()
    by_url = {job.url: job.destination for job in _FakeWorker.started_with}
    assert by_url["https://a.example/v/1"] == special
    assert by_url["https://a.example/v/2"] == tmp_path / "main2"


def test_video_retry_does_not_nest_folders(video_panel, tmp_path):
    from promak.tools.video.models import Stage

    main = tmp_path / "main"
    video_panel.destination_input.setText(str(main))
    _add_links(video_panel, "https://a.example/v/1")
    job = video_panel._jobs[0]
    # what a failed attempt leaves behind: the pipeline moved the job into
    # the video's own sub-folder before failing
    job.destination = main / "Some title"
    job.stage = Stage.FAILED
    video_panel._retry_failed()
    video_panel._start()
    assert _FakeWorker.started_with[0].destination == main


# ============================================================== file tools
@pytest.fixture
def file_panel(qapp, monkeypatch):
    from promak.ui import file_panel as file_module

    monkeypatch.setattr(file_module, "BatchWorker", _FakeWorker)
    _FakeWorker.started_with = None
    panel = file_module.FileQueuePanel()
    yield panel
    panel.deleteLater()


def _pictures(folder: Path, *names):
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in names:
        path = folder / name
        path.write_bytes(b"not really a picture, only its name matters here")
        paths.append(path)
    return paths


def test_files_folder_changed_after_adding_is_the_one_used(file_panel, tmp_path):
    sources = _pictures(tmp_path / "in", "a.png", "b.jpg")
    file_panel.destination_input.setText(str(tmp_path / "old"))
    file_panel.add_files(sources)
    file_panel.destination_input.setText(str(tmp_path / "new"))
    file_panel._start()
    assert [job.destination for job in _FakeWorker.started_with] == [tmp_path / "new"] * 2


def test_files_beside_original_and_back(file_panel, tmp_path):
    sources = _pictures(tmp_path / "in", "a.png")
    file_panel.destination_input.setText(str(tmp_path / "out"))
    file_panel.add_files(sources)
    file_panel.beside_check.setChecked(True)
    assert file_panel._jobs[0].destination == tmp_path / "in"
    # unticking used to leave the file next to its original
    file_panel.beside_check.setChecked(False)
    assert file_panel._jobs[0].destination == tmp_path / "out"
    file_panel._start()
    assert _FakeWorker.started_with[0].destination == tmp_path / "out"


def test_files_change_folder_keeps_its_own_folder(file_panel, tmp_path, monkeypatch):
    from promak.ui import file_panel as file_module

    sources = _pictures(tmp_path / "in", "a.png", "b.png")
    file_panel.destination_input.setText(str(tmp_path / "main"))
    file_panel.add_files(sources)
    file_panel.table.selectRow(1)
    monkeypatch.setattr(
        file_module.QFileDialog, "getExistingDirectory",
        staticmethod(lambda *a, **k: str(tmp_path / "special")),
    )
    file_panel._change_folder_for_selection()
    file_panel.destination_input.setText(str(tmp_path / "main2"))
    file_panel._start()
    by_name = {job.source.name: job.destination for job in _FakeWorker.started_with}
    assert by_name == {"a.png": tmp_path / "main2", "b.png": tmp_path / "special"}


# =========================================================== main window
def test_main_window_side_by_side_and_theme_switch(qapp, monkeypatch):
    from promak.core.config import get_config
    from promak.tools.video import panel as video_module
    from promak.ui.main_window import MainWindow

    monkeypatch.setattr(video_module, "check_dependencies", lambda: [])
    window = MainWindow()
    try:
        # light is what a first start shows
        assert window._theme == "light"
        # the switch is a small icon, not a wide button with words on it
        button = window.theme_button
        assert button.text() == ""
        assert not button.icon().isNull()
        assert button.width() <= 40

        # every tool page shows its blocks in columns, side by side
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QSplitter

        for index in range(window.stack.count()):
            page = window.stack.widget(index)
            splitters = [s for s in page.findChildren(QSplitter) if s.objectName() == "ColumnSplitter"]
            assert splitters, f"page {index} has no columns"
            assert splitters[0].orientation() == Qt.Horizontal
            assert splitters[0].count() == 3

        window.toggle_theme()
        assert window._theme == "dark"
        assert get_config().get("app.theme") == "dark"
        window.toggle_theme()
        assert window._theme == "light"
    finally:
        window.close()
        window.deleteLater()


def test_switch_icons_are_drawn(qapp):
    from promak.ui.theme_icons import moon_icon, sun_icon, switch_icon

    for icon in (sun_icon("#000000"), moon_icon("#ffffff"), switch_icon("light", "#123456")):
        image = icon.pixmap(32, 32).toImage()
        assert not image.isNull()
        painted = sum(
            1 for x in range(32) for y in range(32) if image.pixelColor(x, y).alpha() > 0
        )
        assert painted > 40, "the icon is empty"


def test_left_column_never_cuts_its_content(qapp, monkeypatch):
    """At the smallest window size every column still fits what it holds."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QScrollArea, QSplitter

    from promak.tools.video import panel as video_module
    from promak.ui.main_window import MainWindow

    monkeypatch.setattr(video_module, "check_dependencies", lambda: [])
    window = MainWindow()
    try:
        window.resize(window.minimumSize())
        window.show()
        qapp.processEvents()
        for index in range(window.stack.count()):
            page = window.stack.widget(index)
            window.stack.setCurrentIndex(index)
            qapp.processEvents()
            splitter = next(s for s in page.findChildren(QSplitter) if s.objectName() == "ColumnSplitter")
            left = splitter.widget(0)
            assert isinstance(left, QScrollArea)
            assert left.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
            content = left.widget()
            assert content.width() >= content.minimumSizeHint().width(), (
                f"page {index}: the left column cuts its content "
                f"({content.width()} < {content.minimumSizeHint().width()})"
            )
            # nothing sticks out of the window on the right
            assert splitter.width() <= page.width()
    finally:
        window.close()
        window.deleteLater()
