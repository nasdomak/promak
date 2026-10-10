"""Text from pictures (OCR), on a small picture of text drawn on the spot."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from promak.core.filejobs import FileJob, FileStage
from promak.tools.ocr import engine as e

needs_ocr = pytest.mark.skipif(
    not all(__import__("importlib").util.find_spec(m) for m in ("rapidocr", "onnxruntime", "pikepdf", "pypdfium2")),
    reason="the OCR engine is not installed")


def _font(size: int):
    for name in ("DejaVuSans.ttf", "arial.ttf", "LiberationSans-Regular.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size)


def _page(path: Path, fmt: str = "PNG") -> Path:
    image = Image.new("RGB", (1000, 420), "white")
    draw = ImageDraw.Draw(image)
    draw.text((50, 50), "Invoice number 2026", font=_font(40), fill="black")
    draw.text((50, 250), "Total due 1234 EUR", font=_font(40), fill="black")
    if fmt == "PDF":
        image.save(path, "PDF", resolution=150)
    else:
        image.save(path, dpi=(150, 150))
    return path


def test_words_become_lines_and_paragraphs():
    words = [e.Word("world", 120, 10, 200, 30), e.Word("Hello", 10, 12, 100, 31),
             e.Word("Far", 10, 200, 60, 220), e.Word("below", 70, 199, 150, 221)]
    assert e.words_to_text(words) == "Hello world\n\nFar below"


def test_text_layer_is_invisible_and_placed():
    layer = e.text_layer([e.Word("Città", 0, 0, 100, 20)], 2.0, (0, 0, 600, 800), 0)
    assert layer.startswith(b"q BT 3 Tr")
    assert b"(Citt\xe0)" in layer          # WinAnsi, so accents survive
    # bottom of the word (20 px at 2 px a point = 10 pt from the top) minus a little descent
    assert b"1.00 0.00 0.00 1.00 0.00 791.50 Tm" in layer


@needs_ocr
def test_picture_to_text_and_searchable_pdf(tmp_path):
    import pypdfium2

    source = _page(tmp_path / "scan.png")
    job = FileJob(source=source, destination=tmp_path / "out")
    summary = e.OcrBatch(e.OcrOptions(make=e.MAKE_BOTH)).run([job])
    assert summary["done"] == 1, job.error
    text = (tmp_path / "out" / "scan.txt").read_text(encoding="utf-8")
    assert "Invoice" in text and "1234" in text
    document = pypdfium2.PdfDocument(str(tmp_path / "out" / "scan - searchable.pdf"))
    try:
        textpage = document[0].get_textpage()
        assert "Total" in textpage.get_text_range()
    finally:
        document.close()


@needs_ocr
def test_scanned_pdf_keeps_its_pages(tmp_path):
    import pikepdf

    source = _page(tmp_path / "letter.pdf", "PDF")
    job = FileJob(source=source, destination=tmp_path)
    e.OcrBatch(e.OcrOptions(make=e.MAKE_PDF)).run([job])
    assert job.stage is FileStage.DONE, job.error
    with pikepdf.open(job.output) as pdf:
        assert len(pdf.pages) == 1
        assert "/PromakOCR" in pdf.pages[0].obj.Resources.Font
    # read again: the page now holds text, so it is not read twice
    again = FileJob(source=job.output, destination=tmp_path / "again")
    e.OcrBatch(e.OcrOptions(make=e.MAKE_TEXT)).run([again])
    assert "Invoice" in again.output.read_text(encoding="utf-8")


@pytest.fixture
def qapp(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    widgets = pytest.importorskip("PySide6.QtWidgets")
    for name in ("APPDATA", "XDG_DATA_HOME"):
        monkeypatch.setenv(name, str(tmp_path / "appdata"))
    import promak.core.config as config_module

    monkeypatch.setattr(config_module, "_config", None)
    return widgets.QApplication.instance() or widgets.QApplication([])


def test_ocr_screen(qapp, tmp_path):
    from promak.tools.ocr.panel import OcrPanel

    panel = OcrPanel()
    try:
        panel.destination_input.setText(str(tmp_path / "out"))
        panel.add_files([_page(tmp_path / "scan.png")])
        assert panel.table.rowCount() == 1
        assert panel.validate_before_start() is None
        text_file = tmp_path / "scan.txt"
        text_file.write_text("Hello", encoding="utf-8")
        job = panel._jobs[0]
        job.output = text_file
        panel.on_job_finished(job)
        assert panel.text_view.toPlainText() == "Hello"
    finally:
        panel.deleteLater()
        qapp.processEvents()
