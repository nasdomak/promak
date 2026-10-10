"""Sorting photos and videos by date, on tiny files made on the spot."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path

import pytest
from PIL import Image

from promak.core.dependencies import ffmpeg_exe
from promak.core.fileops import COPY, load_journal, undo_journal
from promak.tools.sortdate import engine as e

FFMPEG = ffmpeg_exe()


def _photo(path: Path, taken: str = "") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    exif = Image.Exif()
    if taken:
        exif.get_ifd(0x8769)[36867] = taken
    Image.new("RGB", (32, 24), "green").save(path, exif=exif)
    return path


def test_folder_codes():
    when = datetime(2026, 7, 12, 10, 30)
    assert e.folder_for(Path("a.jpg"), when, e.DEFAULT_PATTERN) == Path("2026", "07 - July")
    assert e.folder_for(Path("a.mp4"), when, "{kind}/{year}-{mon}-{day} {weekday}") == Path("Videos", "2026-Jul-12 Sunday")
    assert e.folder_for(Path("a.jpg"), None, e.DEFAULT_PATTERN) == Path("No date")
    assert e.check_pattern("{year}/{nope}")
    assert e.check_pattern("plain")
    assert e.check_pattern("{year}:{month}")
    assert e.check_pattern(e.DEFAULT_PATTERN) is None


def test_plan_move_and_undo(tmp_path):
    card = tmp_path / "card"
    a = _photo(card / "IMG_1.JPG", "2026:07:12 10:30:00")
    b = _photo(card / "sub" / "IMG_2.JPG", "2025:12:31 23:59:00")
    c = _photo(card / "no-exif.png")
    os.utime(c, (datetime(2024, 3, 3).timestamp(),) * 2)
    (card / "notes.txt").write_text("not a photo")
    target = tmp_path / "sorted"
    options = e.SortOptions(folders=[card], target=target)
    plan = e.plan_sort(options)
    by_name = {m.source.name: m for m in plan}
    assert set(by_name) == {"IMG_1.JPG", "IMG_2.JPG", "no-exif.png"}
    assert by_name["IMG_1.JPG"].found_by == e.SOURCE_TAKEN
    assert by_name["IMG_1.JPG"].target == target / "2026" / "07 - July" / "IMG_1.JPG"
    assert by_name["IMG_2.JPG"].target.parent == target / "2025" / "12 - December"
    assert by_name["no-exif.png"].found_by == e.SOURCE_FILE
    assert by_name["no-exif.png"].target.parent == target / "2024" / "03 - March"

    result = e.apply_sort(plan, options, journal_dir=tmp_path / "j")
    assert result == {"done": 3, "failed": 0}
    assert not a.exists() and not b.exists()
    assert (target / "2026" / "07 - July" / "IMG_1.JPG").exists()
    assert undo_journal(load_journal(e.TOOL, tmp_path / "j")) == 3
    assert a.exists() and b.exists() and c.exists()
    assert not (target / "2026").exists()  # empty folders made by the run are gone


def test_without_file_date_and_copy(tmp_path):
    card = tmp_path / "card"
    c = _photo(card / "no-exif.png")
    options = e.SortOptions(folders=[card], target=tmp_path / "out", use_file_date=False, action=COPY)
    plan = e.plan_sort(options)
    assert plan[0].target.parent == tmp_path / "out" / "No date"
    e.apply_sort(plan, options, journal_dir=tmp_path / "j")
    assert c.exists() and (tmp_path / "out" / "No date" / "no-exif.png").exists()


def test_same_names_and_identical_files(tmp_path):
    one = _photo(tmp_path / "card" / "a" / "IMG.JPG", "2026:01:05 10:00:00")
    _photo(tmp_path / "card" / "b" / "IMG.JPG", "2026:01:09 10:00:00")
    Image.new("RGB", (40, 40), "red").save(tmp_path / "card" / "b" / "IMG.JPG",
                                           exif=Image.open(one).getexif())
    target = tmp_path / "out"
    plan = e.plan_sort(e.SortOptions(folders=[tmp_path / "card"], target=target))
    assert sorted(m.target.name for m in plan) == ["IMG (2).JPG", "IMG.JPG"]

    # a file identical to one already in place is left alone
    existing = target / "2026" / "01 - January" / "IMG.JPG"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(one.read_bytes())
    plan = e.plan_sort(e.SortOptions(folders=[tmp_path / "card" / "a"], target=target))
    assert plan[0].note and not plan[0].ok


def test_sorting_in_place_leaves_sorted_files_alone(tmp_path):
    folder = tmp_path / "photos"
    _photo(folder / "IMG_1.JPG", "2026:07:12 10:30:00")
    options = e.SortOptions(folders=[folder], target=folder)
    e.apply_sort(e.plan_sort(options), options, journal_dir=tmp_path / "j")
    again = e.plan_sort(options)
    assert len(again) == 1 and again[0].note == "already in its place"


@pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not available")
def test_video_recording_date(tmp_path):
    video = tmp_path / "card" / "clip.mp4"
    video.parent.mkdir()
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=64x64:duration=1", "-metadata", "creation_time=2023-04-05T12:00:00Z",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(video)], check=True)
    plan = e.plan_sort(e.SortOptions(folders=[tmp_path / "card"], target=tmp_path / "out"))
    assert plan[0].found_by == e.SOURCE_VIDEO
    assert plan[0].when.year == 2023 and plan[0].when.month == 4


def test_cli(tmp_path, monkeypatch):
    from promak import cli

    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "appdata"))
    _photo(tmp_path / "card" / "IMG_1.JPG", "2026:07:12 10:30:00")
    assert cli.main(["sortdate", str(tmp_path / "card"), "--to", str(tmp_path / "out")]) == 0
    assert (tmp_path / "card" / "IMG_1.JPG").exists()
    assert cli.main(["sortdate", str(tmp_path / "card"), "--to", str(tmp_path / "out"), "--yes"]) == 0
    assert (tmp_path / "out" / "2026" / "07 - July" / "IMG_1.JPG").exists()
    assert cli.main(["sortdate", "--undo"]) == 0
    assert (tmp_path / "card" / "IMG_1.JPG").exists()


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_sortdate_screen(qapp, tmp_path):
    from promak.tools.sortdate.panel import SortDatePanel

    _photo(tmp_path / "card" / "IMG_1.JPG", "2026:07:12 10:30:00")
    panel = SortDatePanel()
    try:
        panel.folders.set_folders([tmp_path / "card"])
        panel.target_input.setText(str(tmp_path / "out"))
        assert "2026/07 - July/" in panel.example_label.text()
        panel.on_scanned(panel.run_now(panel.scan_task()))
        assert panel.table.rowCount() == 1
        assert panel.table.item(0, 3).text() == "2026/07 - July/"
        assert panel.can_apply()
        panel.pattern_input.setText("{year}/{oops}")
        assert "oops" in panel.example_label.text()
    finally:
        panel.deleteLater()
        qapp.processEvents()
