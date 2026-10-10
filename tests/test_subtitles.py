"""Burning subtitles, on a tiny video made by FFmpeg."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from promak.core.dependencies import ffmpeg_exe
from promak.core.filejobs import FileJob, FileStage
from promak.tools.subtitles import engine as e

FFMPEG = ffmpeg_exe()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not available")


def _clip(path: Path, seconds: int = 2) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    f"color=c=blue:size=320x240:duration={seconds}", "-f", "lavfi", "-i", f"sine=duration={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)], check=True)
    return path


SRT = "1\n00:00:00,000 --> 00:00:01,800\nHello città!\n\n"


def test_subtitles_are_found_next_to_the_video_or_in_a_sister_folder(tmp_path):
    video = tmp_path / "Title" / "mp4" / "Lesson [a1].mp4"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"")
    assert e.find_subtitles(video) is None
    transcript = tmp_path / "Title" / "transcript" / "Lesson [a1].srt"
    transcript.parent.mkdir()
    transcript.write_text(SRT, encoding="utf-8")
    assert e.find_subtitles(video) == transcript
    beside = video.with_name("Lesson [a1].en.vtt")
    beside.write_text("WEBVTT\n", encoding="utf-8")
    assert e.find_subtitles(video) == beside


def test_style():
    assert e.ass_colour("#FF8000") == "&H000080FF"
    style = e.force_style(e.SubtitleOptions(font_size=26, position=8, box=True), "Arial")
    assert style.startswith("FontName=Arial,FontSize=26")
    assert "Alignment=8" in style and "BorderStyle=3" in style
    assert e.SubtitleOptions(colour="white").validate()


@needs_ffmpeg
def test_burn_subtitles(tmp_path):
    from PIL import Image

    video = _clip(tmp_path / "talk.mp4")
    (tmp_path / "talk.srt").write_text(SRT, encoding="cp1252")   # an old Windows file
    job = FileJob(source=video, destination=tmp_path / "out")
    e.SubtitleBatch(e.SubtitleOptions(font_size=30)).run([job])
    assert job.stage is FileStage.DONE, job.error
    frame = tmp_path / "frame.png"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-ss", "1", "-i", str(job.output),
                    "-frames:v", "1", str(frame)], check=True)
    with Image.open(frame) as image:
        rgb = image.convert("RGB")
        white = sum(1 for x in range(0, 320, 2) for y in range(150, 240, 2) if min(rgb.getpixel((x, y))) > 200)
    assert white > 20, "no subtitle drawn"


@needs_ffmpeg
def test_missing_subtitles_are_explained(tmp_path):
    job = FileJob(source=_clip(tmp_path / "alone.mp4", 1), destination=tmp_path)
    e.SubtitleBatch(e.SubtitleOptions()).run([job])
    assert "No subtitles found" in job.error


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_subtitles_screen_shows_what_it_found(qapp, tmp_path):
    from promak.tools.subtitles.panel import CHOSEN, SubtitlesPanel
    from promak.ui.plan_panel import select

    video = tmp_path / "talk.mp4"
    video.write_bytes(b"x")
    (tmp_path / "talk.srt").write_text(SRT, encoding="utf-8")
    panel = SubtitlesPanel()
    try:
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([video])
        assert panel.table.item(0, 1).text() == "talk.srt"
        select(panel.source_combo, CHOSEN)
        assert "Choose the subtitle file" in (panel.validate_before_start() or "")
    finally:
        panel.deleteLater()
        qapp.processEvents()
