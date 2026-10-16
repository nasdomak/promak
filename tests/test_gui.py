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
    assert video_panel.table.item(0, 1).toolTip() == str(new)
    assert video_panel.table.item(0, 1).text() == "new"


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
            # nothing sticks out of the window on the right: when the columns do not
            # fit they slide inside their strip, each one at its full width
            strip = splitter.parentWidget()
            while strip is not None and strip.objectName() != "ColumnStrip":
                strip = strip.parentWidget()
            assert strip is not None, f"page {index}: the columns are not in a strip"
            assert strip.width() <= page.width()
            if strip.is_sliding():
                assert strip.nav.isVisible(), f"page {index}: no buttons to reach the hidden columns"
                for column in range(splitter.count()):
                    widget = splitter.widget(column)
                    assert widget.width() >= widget.minimumWidth() - 1
    finally:
        window.close()
        window.deleteLater()


# ========================================================== small screens
def _strip_of(page):
    from promak.ui.columns import ColumnStrip

    return page.findChildren(ColumnStrip)[0]


def test_narrow_window_columns_slide_and_snap_like_a_magnet(qapp, monkeypatch):
    from promak.tools.video import panel as video_module
    from promak.ui.main_window import MINIMUM_WINDOW, MainWindow

    monkeypatch.setattr(video_module, "check_dependencies", lambda: [])
    window = MainWindow()
    try:
        assert (window.minimumWidth(), window.minimumHeight()) == MINIMUM_WINDOW
        window.resize(*MINIMUM_WINDOW)
        window.show()
        qapp.processEvents()
        strip = _strip_of(window.stack.currentWidget())
        assert strip.is_sliding()
        assert strip.nav.isVisible() and len(strip.nav_buttons) == 3
        # a jump to the activity column brings it into view
        strip._animation.setDuration(0)
        strip.show_column(2)
        qapp.processEvents()
        assert strip.current_column() == 2
        assert strip.nav_buttons[2].isChecked()
        # left half-way between two columns, the strip settles on the nearest one
        stops = strip.column_starts()
        strip.bar.setValue((stops[0] + stops[1]) // 2 - 5)
        strip.snap()
        qapp.processEvents()
        assert strip.bar.value() in stops
        # a wide window shows the three columns and no buttons
        window.resize(2600, 1000)
        qapp.processEvents()
        if not strip.is_sliding():
            assert not strip.nav.isVisible()
    finally:
        window.close()
        window.deleteLater()


def test_zoom_makes_letters_bigger_and_is_remembered(qapp, monkeypatch):
    from promak.core.config import get_config
    from promak.tools.video import panel as video_module
    from promak.ui.main_window import MainWindow
    from promak.ui.theme import ZOOM_STEPS, normalise_zoom, stylesheet, zoom_step

    assert normalise_zoom("nonsense") == 1.0 and normalise_zoom(3) == ZOOM_STEPS[-1]
    assert zoom_step(1.0, 1) == 1.1 and zoom_step(1.0, -1) == 0.9 and zoom_step(1.6, 0) == 1.0
    assert "font-size: 13px" in stylesheet("light", 1.0)
    assert "font-size: 16.2px" in stylesheet("light", 1.25) or "font-size: 16.25px" in stylesheet("light", 1.25)

    monkeypatch.setattr(video_module, "check_dependencies", lambda: [])
    window = MainWindow()
    try:
        assert window.zoom_reset_button.text() == "100 %"
        width = window.sidebar.width()
        window.change_zoom(1)
        assert window.zoom_reset_button.text() == "110 %"
        assert get_config().get("app.zoom") == 1.1
        assert window.sidebar.width() > width
        for _ in range(20):
            window.change_zoom(1)
        assert not window.zoom_in_button.isEnabled()          # the biggest step
        window.change_zoom(0)
        assert window.zoom_reset_button.text() == "100 %" and window.sidebar.width() == width
    finally:
        window.close()
        window.deleteLater()


def test_window_never_larger_than_the_screen(qapp, monkeypatch):
    from promak.tools.video import panel as video_module
    from promak.ui.main_window import MINIMUM_WINDOW, MainWindow

    monkeypatch.setattr(video_module, "check_dependencies", lambda: [])
    monkeypatch.setattr(MainWindow, "_available_size", staticmethod(lambda: (1280, 720)))
    window = MainWindow()
    try:
        assert window.width() <= 1280 - 16 and window.height() <= 720 - 40
        assert window._fitting_size(400, 300) == MINIMUM_WINDOW
    finally:
        window.close()
        window.deleteLater()


# ======================================================== words to remove
def test_word_filter_box_starts_off_but_remembers_the_words(qapp):
    from promak.core.config import get_config
    from promak.ui.word_filter_box import WordFilterBox

    box = WordFilterBox()
    box.load(get_config())
    assert not box.enable_check.isChecked() and box.phrases_text() == ""
    box.enable_check.setChecked(True)
    assert box.problem()                                       # ticked with nothing written
    box.phrases_input.setText("vaffanculo; you know")
    box.case_check.setChecked(True)
    assert box.problem() == "" and box.phrases_text() == "vaffanculo; you know"
    assert box.word_filter().active and box.match_case()
    box.save(get_config())
    again = WordFilterBox()
    again.load(get_config())
    # the words and the case choice come back; the tick does not
    assert again.phrases_input.text() == "vaffanculo; you know" and again.case_check.isChecked()
    assert not again.enable_check.isChecked() and again.phrases_text() == ""


def test_video_screen_passes_the_words_to_remove(video_panel, tmp_path):
    video_panel.transcribe_check.setChecked(True)
    video_panel.word_filter_box.enable_check.setChecked(True)
    video_panel.word_filter_box.phrases_input.setText("damn")
    options = video_panel._current_options()
    assert options.drop_words == "damn" and not options.drop_match_case
    video_panel.word_filter_box.enable_check.setChecked(False)
    assert video_panel._current_options().drop_words == ""
    video_panel.transcribe_check.setChecked(False)
    assert not video_panel.word_filter_box.isEnabled()


def test_subtitles_screen_passes_the_words_to_remove(qapp):
    from promak.tools.subtitles.panel import SubtitlesPanel

    panel = SubtitlesPanel()
    try:
        panel.word_filter_box.enable_check.setChecked(True)
        panel.word_filter_box.phrases_input.setText("damn")
        assert panel.current_options().drop_words == "damn"
        panel.word_filter_box.phrases_input.setText("")
        assert "no word" in (panel.validate_before_start() or "")
    finally:
        panel.deleteLater()


# ======================================================== books to markdown
def test_books_to_markdown_screen(qapp, tmp_path):
    from promak.tools.booknotes.panel import BookNotesPanel
    from promak.tools.booknotes.pdf_reader import PICTURES_NONE

    panel = BookNotesPanel()
    try:
        book = tmp_path / "book.txt"
        book.write_text("A short book.", encoding="utf-8")
        (tmp_path / "skip.xyz").write_text("?")
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([book, tmp_path / "skip.xyz"])
        assert panel.table.rowCount() == 1
        assert panel.validate_before_start() is None
        options = panel.current_options()
        assert options.split and options.ocr and options.page_marks and options.drop_words == ""
        panel.pictures_combo.setCurrentIndex(panel.pictures_combo.findData(PICTURES_NONE))
        assert not panel.size_combo.isEnabled()
        panel.word_filter_box.enable_check.setChecked(True)
        panel.word_filter_box.phrases_input.setText("short")
        assert panel.current_options().drop_words == "short"
        panel.save_settings()
        again = BookNotesPanel()
        try:
            assert again.current_options().pictures == PICTURES_NONE
            assert again.current_options().drop_words == ""          # the tick is not remembered
            assert again.word_filter_box.phrases_input.text() == "short"
        finally:
            again.deleteLater()
    finally:
        panel.deleteLater()
        qapp.processEvents()


def test_renamer_screen_previews_and_renames(qapp, tmp_path, monkeypatch):
    from promak.tools.renamer import panel as renamer_module

    monkeypatch.setattr(renamer_module.QMessageBox, "question",
                        staticmethod(lambda *a, **k: renamer_module.QMessageBox.Yes))
    root = tmp_path / "albums"
    for name in ("Summer", "Winter 2", "Winter 10"):
        (root / name).mkdir(parents=True)
    page = renamer_module.RenamerPanel()
    try:
        page.set_folder(root)
        assert page.table.rowCount() == 3
        assert page.table.item(0, 1).text() == "01 - Summer"
        assert page.start_button.isEnabled()
        page._apply()
        assert sorted(p.name for p in root.iterdir()) == ["01 - Summer", "02 - Winter 2", "03 - Winter 10"]
        assert page.undo_button.isEnabled()
        page._undo()
        assert sorted(p.name for p in root.iterdir()) == ["Summer", "Winter 10", "Winter 2"]
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_renamer_custom_code_and_saved_codes(qapp, tmp_path):
    from promak.tools.renamer import panel as renamer_module
    from promak.tools.renamer.engine import STYLE_CUSTOM

    root = tmp_path / "jobs"
    for name in ("Kitchen", "Garden"):
        (root / name).mkdir(parents=True)
    page = renamer_module.RenamerPanel()
    try:
        page.set_folder(root)
        page.style_combo.setCurrentIndex(page.style_combo.findData(STYLE_CUSTOM))
        page.pattern_input.setText("JOB-{n:3} {name:upper}")
        assert page.table.item(0, 1).text() == "JOB-001 GARDEN"
        page._save_code()
        assert page.saved_codes() == ["JOB-{n:3} {name:upper}"]
        page.pattern_input.setText("{n} {nope}")
        assert not page.start_button.isEnabled()
        assert "nope" in page.summary_label.text()
        page.saved_combo.setCurrentIndex(page.saved_combo.findData("JOB-{n:3} {name:upper}"))
        page._forget_code()
        assert page.saved_codes() == []
    finally:
        page.deleteLater()
        qapp.processEvents()
