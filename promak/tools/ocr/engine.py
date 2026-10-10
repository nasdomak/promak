"""Reading the text in pictures and scanned PDFs (OCR), offline.

The reading is done by RapidOCR (Apache-2.0) on ONNX Runtime (MIT).  Its
multilingual model ships inside the package, so nothing is downloaded and
nothing leaves the computer; it reads English, Italian, French, German,
Spanish, Portuguese and the other languages written in the Latin alphabet
(plus Chinese and Japanese).

Two results, alone or together:

* **text** (``.txt``) - the words of every page, line by line, in reading order;
* **searchable PDF** - the page as it was, with the words laid invisibly on
  top, so the PDF can be searched, and its text selected and copied.  For a
  PDF the original pages are kept as they are (vector text, quality); for a
  picture a page is made from it.

Pages of a PDF that already hold text can be left alone.  Nothing here
imports Qt.
"""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.core.imaging import RASTER_EXTENSIONS, ImageToolError, flatten, human_size
from promak.tools.pdf.engine import output_path, require_pdfium, require_pikepdf

log = logging.getLogger(__name__)

ACCEPTED_EXTENSIONS = (".pdf",) + RASTER_EXTENSIONS

MAKE_TEXT = "text"
MAKE_PDF = "pdf"
MAKE_BOTH = "both"
MAKES = [
    ("Text file (.txt)", MAKE_TEXT),
    ("Searchable PDF (the page as it is, with selectable text)", MAKE_PDF),
    ("Both", MAKE_BOTH),
]
DPI_CHOICES = [("Normal pages (200 dpi)", 200), ("Small print (300 dpi)", 300), ("Quick (150 dpi)", 150)]

LANGUAGES_TEXT = ("Reads English, Italian, French, German, Spanish, Portuguese, Dutch and the other "
                  "languages written in the Latin alphabet, plus Chinese and Japanese - all built in.")


class OcrError(ImageToolError):
    """An OCR problem told in plain words."""


@dataclass
class OcrOptions:
    make: str = MAKE_TEXT
    dpi: int = 200                  # for PDF pages
    skip_text_pages: bool = True    # PDF pages that already have text are not read again
    min_confidence: float = 0.5     # words read with less certainty are dropped
    suffix: str = ""
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.make not in (MAKE_TEXT, MAKE_PDF, MAKE_BOTH):
            return "Choose what to make: a text file, a searchable PDF or both."
        return None


@dataclass
class Word:
    """A piece of text and where it sits, in pixels of the page picture."""

    text: str
    left: float
    top: float
    right: float
    bottom: float

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)


# --------------------------------------------------------------- the reader
_engine = None
_engine_lock = threading.Lock()


def require_reader():
    """The OCR engine, started once (it takes a few seconds)."""
    global _engine
    with _engine_lock:
        if _engine is None:
            try:
                from rapidocr import RapidOCR
            except ImportError as exc:
                raise OcrError("The OCR engine is missing. Run install_windows.bat again, or:  "
                               "pip install -U rapidocr onnxruntime") from exc
            try:
                _engine = RapidOCR(params={"Global.log_level": "critical"})
            except Exception as exc:  # pragma: no cover - a broken installation
                raise OcrError(f"The OCR engine could not start ({exc}). Run install_windows.bat again, "
                               "or:  pip install -U rapidocr onnxruntime") from exc
        return _engine


def read_words(image, min_confidence: float = 0.5) -> List[Word]:
    """Every piece of text found in a Pillow picture."""
    import numpy

    reader = require_reader()
    rgb = flatten(image) if image.mode != "RGB" else image
    result = reader(numpy.array(rgb))
    if result is None or result.txts is None or result.boxes is None:
        return []
    words: List[Word] = []
    scores = result.scores if result.scores is not None else [1.0] * len(result.txts)
    for text, box, score in zip(result.txts, result.boxes, scores):
        text = str(text).strip()
        if not text or float(score) < min_confidence:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        words.append(Word(text, min(xs), min(ys), max(xs), max(ys)))
    return words


def words_to_lines(words: Sequence[Word]) -> List[List[Word]]:
    """Group pieces of text into lines, top to bottom, left to right."""
    lines: List[List[Word]] = []
    for word in sorted(words, key=lambda w: (w.top + w.bottom) / 2):
        centre = (word.top + word.bottom) / 2
        for line in lines:
            ref = line[0]
            if abs((ref.top + ref.bottom) / 2 - centre) <= 0.5 * min(ref.height, word.height):
                line.append(word)
                break
        else:
            lines.append([word])
    for line in lines:
        line.sort(key=lambda w: w.left)
    lines.sort(key=lambda line: min(w.top for w in line))
    return lines


def words_to_text(words: Sequence[Word]) -> str:
    """Plain text; an empty line where the gap between two lines is large."""
    lines = words_to_lines(words)
    out: List[str] = []
    previous_bottom = None
    for line in lines:
        top = min(w.top for w in line)
        height = sum(w.height for w in line) / len(line)
        if previous_bottom is not None and top - previous_bottom > 1.2 * height:
            out.append("")
        out.append(" ".join(w.text for w in line))
        previous_bottom = max(w.bottom for w in line)
    return "\n".join(out).strip()


# ----------------------------------------------------------- invisible text
def _pdf_string(text: str) -> bytes:
    """Text for the built-in Helvetica font (WinAnsi): what it cannot show becomes '?'."""
    raw = text.encode("cp1252", errors="replace")
    return b"(" + raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def text_layer(words: Sequence[Word], scale: float, crop: Tuple[float, float, float, float],
               rotate: int = 0) -> bytes:
    """A content stream that writes ``words`` invisibly over a page.

    ``scale`` is pixels per point of the page picture; ``crop`` is the
    page's visible box; ``rotate`` its /Rotate, so the words land where they
    are seen even on a page that is turned.
    """
    x0, y0, x1, y1 = crop
    parts = [b"q BT 3 Tr"]          # render mode 3: neither filled nor stroked = invisible
    for word in words:
        size = max(1.0, word.height / scale * 0.85)
        u, v = word.left / scale, word.bottom / scale - 0.15 * word.height / scale
        width = max(1.0, (word.right - word.left) / scale)
        if rotate == 90:
            matrix = (0, 1, -1, 0, x0 + v, y0 + u)
        elif rotate == 180:
            matrix = (-1, 0, 0, -1, x1 - u, y0 + v)
        elif rotate == 270:
            matrix = (0, -1, 1, 0, x1 - v, y1 - u)
        else:
            matrix = (1, 0, 0, 1, x0 + u, y1 - v)
        # stretch the words to the width they have on the page (Helvetica: ~0.5 em a letter)
        stretch = max(10.0, min(500.0, width / (max(1, len(word.text)) * 0.5 * size) * 100))
        parts.append(b"/PromakOCR %.2f Tf %.1f Tz %s Tm %s Tj" % (
            size, stretch, " ".join(f"{value:.2f}" for value in matrix).encode("ascii"), _pdf_string(word.text)))
    parts.append(b"ET Q")
    return b"\n".join(parts)


def _add_font(pdf, page) -> None:
    import pikepdf

    resources = page.obj.get("/Resources")
    if resources is None:
        page.obj.Resources = resources = pikepdf.Dictionary()
    fonts = resources.get("/Font")
    if fonts is None:
        resources.Font = fonts = pikepdf.Dictionary()
    fonts.PromakOCR = pdf.make_indirect(pikepdf.Dictionary(
        Type=pikepdf.Name.Font, Subtype=pikepdf.Name.Type1, BaseFont=pikepdf.Name.Helvetica,
        Encoding=pikepdf.Name.WinAnsiEncoding))


def add_text_layer(pdf, page, words: Sequence[Word], scale: float) -> None:
    """Lay ``words`` invisibly over one page of a pikepdf document."""
    if not words:
        return
    box = page.obj.get("/CropBox") or page.obj.get("/MediaBox")
    crop = tuple(float(value) for value in box)
    rotate = int(page.obj.get("/Rotate", 0)) % 360
    _add_font(pdf, page)
    page.contents_add(pdf.make_stream(text_layer(words, scale, crop, rotate)), prepend=False)


def picture_page(pdf, image, dpi: float):
    """Add a page holding ``image`` at ``dpi`` to a pikepdf document; returns it."""
    import pikepdf

    rgb = flatten(image) if image.mode not in ("RGB", "L") else image
    buffer = io.BytesIO()
    rgb.save(buffer, "JPEG", quality=85, optimize=True)
    width_pt, height_pt = rgb.width * 72.0 / dpi, rgb.height * 72.0 / dpi
    xobject = pikepdf.Stream(pdf, buffer.getvalue())
    xobject.Type, xobject.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
    xobject.Width, xobject.Height, xobject.BitsPerComponent = rgb.width, rgb.height, 8
    xobject.ColorSpace = pikepdf.Name.DeviceGray if rgb.mode == "L" else pikepdf.Name.DeviceRGB
    xobject.Filter = pikepdf.Name.DCTDecode
    content = b"q %.3f 0 0 %.3f 0 0 cm /Scan Do Q" % (width_pt, height_pt)
    page = pikepdf.Page(pikepdf.Dictionary(
        Type=pikepdf.Name.Page, MediaBox=[0, 0, width_pt, height_pt],
        Resources=pikepdf.Dictionary(XObject=pikepdf.Dictionary(Scan=xobject)),
        Contents=pdf.make_stream(content)))
    pdf.pages.append(page)
    return pdf.pages[-1]


# --------------------------------------------------------------- the engine
class OcrBatch(BatchEngine):
    """Reads the text of every picture and PDF in the queue."""

    what = "file(s)"

    def __init__(self, options: OcrOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def _targets(self, job: FileJob) -> Tuple[Optional[Path], Optional[Path]]:
        suffix = self.options.suffix.strip()
        text = pdf = None
        if self.options.make in (MAKE_TEXT, MAKE_BOTH):
            text = output_path(job, suffix, ".txt", self.options.overwrite)
        if self.options.make in (MAKE_PDF, MAKE_BOTH):
            pdf = output_path(job, suffix or " - searchable", ".pdf", self.options.overwrite)
        return text, pdf

    def process_one(self, job: FileJob, report) -> None:
        report(3, "starting the OCR engine")
        require_reader()
        text_target, pdf_target = self._targets(job)
        if job.source.suffix.lower() == ".pdf":
            pages_text = self._pdf(job, pdf_target, report)
        else:
            pages_text = self._picture(job, pdf_target, report)
        words = sum(len(page.split()) for page in pages_text)
        if text_target is not None:
            body = "\n\n\f".join(pages_text) if len(pages_text) > 1 else (pages_text[0] if pages_text else "")
            text_target.write_text(body.replace("\f", "") + "\n", encoding="utf-8")
        job.output = text_target or pdf_target
        job.output_bytes = sum(p.stat().st_size for p in (text_target, pdf_target) if p is not None)
        job.info["words"] = str(words)
        job.info["pages"] = str(len(pages_text))
        if not words:
            job.message = "no text found - is it a picture of text?"
        else:
            made = " + ".join(p.suffix.lstrip(".").upper() for p in (text_target, pdf_target) if p is not None)
            job.message = f"{words} words, {made} ({human_size(job.output_bytes)})"

    # ------------------------------------------------------------ pictures
    def _picture(self, job: FileJob, pdf_target: Optional[Path], report) -> List[str]:
        from PIL import Image, ImageOps

        try:
            with Image.open(job.source) as opened:
                opened.load()
                dpi = opened.info.get("dpi", (0, 0))[0] or 150
                image = ImageOps.exif_transpose(opened)
        except Exception as exc:
            raise OcrError(f"The picture cannot be opened: {exc}") from exc
        report(20, "reading")
        self.check_cancel()
        words = read_words(image, self.options.min_confidence)
        if pdf_target is not None:
            pikepdf = require_pikepdf()
            with pikepdf.new() as pdf:
                page = picture_page(pdf, image, float(dpi))
                add_text_layer(pdf, page, words, float(dpi) / 72.0)
                _save(pdf, pdf_target)
        return [words_to_text(words)]

    # ---------------------------------------------------------------- PDFs
    def _pdf(self, job: FileJob, pdf_target: Optional[Path], report) -> List[str]:
        pdfium = require_pdfium()
        pikepdf = require_pikepdf()
        try:
            document = pdfium.PdfDocument(str(job.source))
        except pdfium.PdfiumError as exc:
            if "password" in str(exc).lower():
                raise OcrError("This PDF needs a password: remove it first with the PDF toolbox.") from exc
            raise OcrError(f"This file cannot be read as a PDF ({exc}).") from exc
        scale = max(72, int(self.options.dpi)) / 72.0
        texts: List[str] = []
        layered = pikepdf.open(str(job.source)) if pdf_target is not None else None
        try:
            count = len(document)
            for index in range(count):
                self.check_cancel()
                page = document[index]
                try:
                    textpage = page.get_textpage()
                    try:
                        existing = textpage.get_text_range().strip()
                    finally:
                        textpage.close()
                    if existing and self.options.skip_text_pages:
                        texts.append(existing)
                        report(5 + 95 * (index + 1) / count, f"page {index + 1} of {count} already has text")
                        continue
                    image = page.render(scale=scale).to_pil()
                finally:
                    page.close()
                report(5 + 95 * (index + 0.5) / count, f"reading page {index + 1} of {count}")
                words = read_words(image, self.options.min_confidence)
                texts.append(words_to_text(words))
                if layered is not None:
                    add_text_layer(layered, layered.pages[index], words, scale)
            if layered is not None:
                _save(layered, pdf_target)
        finally:
            document.close()
            if layered is not None:
                layered.close()
        return texts

    def describe_result(self, job: FileJob) -> str:
        return job.message or super().describe_result(job)


def _save(pdf, target: Path) -> None:
    from promak.tools.pdf.engine import save_pdf

    save_pdf(pdf, target)

