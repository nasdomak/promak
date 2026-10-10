"""Cutting silences, on a tiny recording made by FFmpeg."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from promak.core.dependencies import ffmpeg_exe
from promak.core.filejobs import FileJob, FileStage
from promak.core.media import media_facts
from promak.tools.silence import engine as e

FFMPEG = ffmpeg_exe()
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg is not available")


def _talk(path: Path) -> Path:
    """2 s of tone, 3 s of silence, 2 s of tone, 2 s of silence."""
    graph = ("sine=f=440:d=2[a];anullsrc=r=44100:cl=mono,atrim=0:3[b];sine=f=440:d=2[c];"
             "anullsrc=r=44100:cl=mono,atrim=0:2[d];[a][b][c][d]concat=n=4:v=0:a=1[out]")
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-filter_complex", graph,
                    "-map", "[out]", str(path)], check=True)
    return path


def test_segments_keep_a_little_of_each_pause():
    segments = e.speech_segments([(2.0, 5.0), (7.0, 9.0)], 9.0, 0.2)
    assert segments == [(0.0, 2.2), (4.8, 7.2)]
    assert e.speech_segments([], 5.0, 0.2) == [(0.0, 5.0)]
    assert e.speech_segments([(0.0, 1.0)], 4.0, 0.2) == [(0.8, 4.0)]
    assert e.SilenceOptions(min_silence=0.3, keep=0.2).validate()


@needs_ffmpeg
def test_silences_found_and_cut_from_sound(tmp_path):
    source = _talk(tmp_path / "talk.mp3")
    silences = e.detect_silences(source, -35, 0.8, media_facts(source).duration)
    assert len(silences) == 2
    assert abs(silences[0][0] - 2.0) < 0.15 and abs(silences[0][1] - 5.0) < 0.15
    job = FileJob(source=source, destination=tmp_path / "out")
    e.SilenceBatch(e.SilenceOptions()).run([job])
    assert job.stage is FileStage.DONE, job.error
    assert job.output.suffix == ".mp3"
    assert 4.0 < media_facts(job.output).duration < 5.6


@needs_ffmpeg
def test_video_and_nothing_to_cut(tmp_path):
    sound = _talk(tmp_path / "talk.m4a")
    video = tmp_path / "talk.mkv"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                    "testsrc=size=160x120:rate=25:duration=9", "-i", str(sound), "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video)], check=True)
    job = FileJob(source=video, destination=tmp_path / "out")
    e.SilenceBatch(e.SilenceOptions()).run([job])
    assert job.stage is FileStage.DONE, job.error
    facts = media_facts(job.output)
    assert job.output.suffix == ".mp4" and facts.has_video and facts.duration < 6

    tone = tmp_path / "tone.wav"
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", "sine=d=2",
                    str(tone)], check=True)
    job = FileJob(source=tone, destination=tmp_path / "out")
    e.SilenceBatch(e.SilenceOptions()).run([job])
    assert job.stage is FileStage.SKIPPED


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_silence_screen(qapp, tmp_path):
    from promak.tools.silence.panel import SilencePanel

    recording = tmp_path / "lesson.mp3"
    recording.write_bytes(b"x")
    panel = SilencePanel()
    try:
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([recording])
        assert panel.table.rowCount() == 1
        panel.keep_spin.setValue(0.5)
        panel.length_spin.setValue(0.8)
        assert "half" in (panel.current_options().validate() or "")
    finally:
        panel.deleteLater()
        qapp.processEvents()
