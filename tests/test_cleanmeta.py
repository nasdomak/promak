"""Removing hidden data, on tiny files made on the spot."""

from __future__ import annotations

import os

import pytest
from PIL import Image, PngImagePlugin

from promak.core.filejobs import FileJob, FileStage
from promak.tools.cleanmeta import engine as e


def _exif(orientation: int = 6):
    exif = Image.Exif()
    exif[0x010F], exif[0x0110], exif[0x0112] = "Canon", "EOS 90D", orientation
    exif.get_ifd(0x8769)[0x9003] = "2026:07:12 10:00:00"
    exif.get_ifd(0x8769)[0xA431] = "SN12345"
    gps = exif.get_ifd(0x8825)
    gps[1], gps[2], gps[3], gps[4] = "N", (41.0, 53.0, 24.0), "E", (12.0, 29.0, 32.0)
    return exif


def _labels(findings):
    return {f.label for f in findings}


def test_jpeg_loses_gps_and_camera_but_not_its_pixels(tmp_path):
    source = tmp_path / "photo.jpg"
    Image.effect_noise((80, 60), 40).convert("RGB").save(source, exif=_exif(), quality=90, comment=b"note")
    found = e.inspect(source)
    assert "GPS position (where it was taken)" in _labels(found)
    assert any(f.value == "41.89000, 12.49222" for f in found)
    assert "Camera serial number" in _labels(found)
    target = tmp_path / "clean.jpg"
    e.clean_file(source, target, e.CleanOptions())
    left = e.inspect(target)
    assert _labels(left) == {"Orientation (this side up)"}
    with Image.open(source) as a, Image.open(target) as b:
        assert a.tobytes() == b.tobytes()           # not re-encoded
        assert b.getexif().get(0x0112) == 6
    e.clean_file(source, target, e.CleanOptions(keep_orientation=False))
    assert e.inspect(target) == []


def test_png_and_webp(tmp_path):
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Marco")
    png = tmp_path / "a.png"
    Image.new("RGB", (20, 20), "red").save(png, pnginfo=info)
    assert "Author" in _labels(e.inspect(png))
    e.clean_file(png, tmp_path / "a-clean.png", e.CleanOptions())
    assert e.inspect(tmp_path / "a-clean.png") == []

    webp = tmp_path / "b.webp"
    Image.new("RGB", (20, 20), "blue").save(webp, exif=_exif(1))
    assert "Camera model" in _labels(e.inspect(webp))
    e.clean_file(webp, tmp_path / "b-clean.webp", e.CleanOptions())
    assert e.inspect(tmp_path / "b-clean.webp") == []
    with Image.open(tmp_path / "b-clean.webp") as image:
        assert image.size == (20, 20)


def test_pdf_properties(tmp_path):
    pytest.importorskip("pikepdf")
    source = tmp_path / "d.pdf"
    Image.new("RGB", (50, 50)).save(source, "PDF", title="Secret", author="Marco Rossi")
    assert "Author" in _labels(e.inspect(source))
    e.clean_file(source, tmp_path / "c.pdf", e.CleanOptions())
    assert e.inspect(tmp_path / "c.pdf") == []


def test_office_properties_and_comments_reported(tmp_path):
    docx = pytest.importorskip("docx")
    document = docx.Document()
    document.add_paragraph("Hello")
    document.core_properties.author = "Marco"
    document.core_properties.last_modified_by = "Anna"
    source = tmp_path / "o.docx"
    document.save(str(source))
    found = e.inspect(source)
    assert {"Author", "Last edited by"} <= _labels(found)
    e.clean_file(source, tmp_path / "c.docx", e.CleanOptions())
    assert e.inspect(tmp_path / "c.docx") == []
    assert docx.Document(str(tmp_path / "c.docx")).paragraphs[0].text == "Hello"


def test_engine_skips_clean_files_and_cli(tmp_path):
    from promak import cli

    plain = tmp_path / "plain.png"
    Image.new("RGB", (10, 10)).save(plain)
    job = FileJob(source=plain, destination=tmp_path / "out")
    e.CleanBatch(e.CleanOptions()).run([job])
    assert job.stage is FileStage.SKIPPED

    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (10, 10)).save(photo, exif=_exif())
    assert cli.main(["clean", str(photo), "--out", str(tmp_path / "share"), "--quiet"]) == 0
    assert (tmp_path / "share" / "photo-clean.jpg").exists()


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_cleanmeta_screen_shows_what_was_found(qapp, tmp_path):
    from promak.tools.cleanmeta.panel import CleanMetaPanel

    photo = tmp_path / "photo.jpg"
    Image.new("RGB", (10, 10)).save(photo, exif=_exif())
    panel = CleanMetaPanel()
    try:
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([photo])
        assert panel.table.item(0, 1).text().startswith("GPS position")
        panel.table.selectRow(0)
        labels = [panel.found_table.item(r, 0).text() for r in range(panel.found_table.rowCount())]
        assert "! GPS position (where it was taken)" in labels
    finally:
        panel.deleteLater()
        qapp.processEvents()
