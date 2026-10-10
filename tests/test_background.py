"""Removing backgrounds.  The network itself is replaced by a stand-in:
the tests must not download a model, so they check everything around it."""

from __future__ import annotations

import os

import pytest
from PIL import Image, ImageDraw

from promak.core.filejobs import FileJob, FileStage
from promak.tools.background import engine as e


@pytest.fixture
def fake_network(monkeypatch, tmp_path):
    """A 'network' that keeps the red circle and drops the green background."""
    monkeypatch.setattr(e, "models_dir", lambda: tmp_path / "models")
    monkeypatch.setattr(e, "require_session", lambda model: "session")

    def remove(image, options, session=None):
        rgba = image.convert("RGBA")
        alpha = image.convert("RGB").point(lambda v: v).split()[0].point(lambda v: 255 if v > 150 else 0)
        rgba.putalpha(alpha)
        if options.crop:
            rgba = rgba.crop(alpha.getbbox())
        return rgba

    monkeypatch.setattr(e, "remove_background", remove)


def _photo(path):
    image = Image.new("RGB", (200, 150), (30, 160, 60))
    ImageDraw.Draw(image).ellipse((60, 30, 140, 110), fill=(220, 40, 40))
    image.save(path)
    return path


def test_transparent_png(tmp_path, fake_network):
    job = FileJob(source=_photo(tmp_path / "product.jpg"), destination=tmp_path / "out")
    e.BackgroundBatch(e.BackgroundOptions(model="u2netp")).run([job])
    assert job.stage is FileStage.DONE, job.error
    assert job.output.name == "product-no-background.png"
    with Image.open(job.output) as image:
        assert image.mode == "RGBA"
        assert image.getpixel((5, 5))[3] == 0 and image.getpixel((100, 70))[3] == 255


def test_colour_and_crop(tmp_path, fake_network):
    job = FileJob(source=_photo(tmp_path / "p.png"), destination=tmp_path)
    e.BackgroundBatch(e.BackgroundOptions(model="u2netp", background=e.COLOUR, colour="#0000FF", crop=True)).run([job])
    assert job.output.suffix == ".jpg"
    with Image.open(job.output) as image:
        assert image.size[0] < 100            # trimmed to the circle
        r, g, b = image.convert("RGB").getpixel((0, 0))
        assert b > 200 and r < 60              # the corners are the new colour


def test_model_state_and_options(tmp_path, monkeypatch):
    monkeypatch.setattr(e, "models_dir", lambda: tmp_path / "models")
    assert not e.model_ready("u2netp")
    (e.model_home() / "models" / "u2netp").mkdir(parents=True)
    (e.model_home() / "models" / "u2netp" / "u2netp.onnx").write_bytes(b"x")
    assert e.model_ready("u2netp")
    assert e.BackgroundOptions(model="nope").validate()
    assert e.BackgroundOptions(background=e.COLOUR, colour="blue").validate()


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_background_screen(qapp, tmp_path):
    from promak.tools.background.panel import BackgroundPanel
    from promak.ui.plan_panel import select

    panel = BackgroundPanel()
    try:
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([_photo(tmp_path / "a.png")])
        assert panel.table.rowCount() == 1
        assert "MB" in panel.model_label.text() or "offline" in panel.model_label.text()
        select(panel.background_combo, e.COLOUR)
        assert not panel.colour_field.isHidden()
        panel.table.selectRow(0)
    finally:
        panel.deleteLater()
        qapp.processEvents()
