"""The screen recorder: the commands it builds, and a real short recording
of FFmpeg's moving test picture (no screen is needed)."""

from __future__ import annotations

import os
import time

import pytest

from promak.core.dependencies import ffmpeg_exe
from promak.core.media import media_facts
from promak.tools.screenrec import engine as e

needs_ffmpeg = pytest.mark.skipif(ffmpeg_exe() is None, reason="FFmpeg is not available")


@needs_ffmpeg
def test_commands_for_each_system(tmp_path):
    region = e.Region(10, 20, 641, 481)
    gdi = e.build_command(e.RecordOptions(method=e.GDIGRAB, region=region), tmp_path / "x.mkv")
    assert gdi[gdi.index("-f") + 1] == "gdigrab" and "640x480" in gdi and "desktop" in gdi
    assert gdi[gdi.index("-offset_x") + 1] == "10"
    dda = e.build_command(e.RecordOptions(method=e.DDAGRAB, region=region), tmp_path / "x.mkv")
    assert any(part.startswith("ddagrab=") and "offset_y=20" in part for part in dda)
    assert "hwdownload,format=bgra,format=yuv420p" in dda
    x11 = e.build_command(e.RecordOptions(method=e.X11GRAB, region=region, display=":5"), tmp_path / "x.mkv")
    assert ":5+10,20" in x11
    mic = e.build_command(e.RecordOptions(method=e.GDIGRAB, microphone="Mic (USB)"), tmp_path / "x.mkv")
    assert "1:a:0" in mic


def test_regions():
    assert e.parse_region("") is None
    assert e.parse_region("5,6 100x50") == e.Region(5, 6, 100, 50)
    with pytest.raises(ValueError):
        e.parse_region("100x50")
    assert e.RecordOptions(region=e.Region(0, 0, 5, 5)).validate()


@needs_ffmpeg
def test_a_short_recording(tmp_path):
    recorder = e.Recorder(e.RecordOptions(folder=tmp_path, method=e.TEST, region=e.Region(0, 0, 160, 120),
                                          frame_rate=15))
    recorder.start()
    time.sleep(1.5)
    made = recorder.stop()
    assert made.suffix == ".mp4" and made.parent == tmp_path
    facts = media_facts(made)
    assert facts.has_video and (facts.width, facts.height) == (160, 120)
    assert 0.5 < facts.duration < 6
    assert not list(tmp_path.glob("*.mkv"))


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


@needs_ffmpeg
def test_recorder_screen_start_and_stop(qapp, tmp_path):
    from promak.tools.screenrec.panel import AREA, ScreenRecorderPanel
    from promak.ui.plan_panel import select

    panel = ScreenRecorderPanel()
    try:
        panel.folder_input.setText(str(tmp_path))
        select(panel.area_combo, AREA)
        panel.region = None
        panel._on_area_changed()
        assert not panel.can_apply()          # a rectangle must be dragged first
        panel.region = e.Region(0, 0, 160, 120)
        panel.method_override = e.TEST
        panel.apply()
        assert panel.recorder is not None and panel.apply_button.text() == "Stop recording"
        time.sleep(1.2)
        panel.stop()
        assert panel.recorder is None
        assert panel.table.rowCount() == 1
        assert list(tmp_path.glob("*.mp4"))
    finally:
        panel.deleteLater()
        qapp.processEvents()
