"""Books and documents to Markdown notes, with their pictures.

A heavy PDF is a poor thing to hand to an AI or to keep in a "second
brain": it is large, its text is broken into lines and pages, and its
drawings are invisible to search.  This tool rewrites each book as a folder
of plain Markdown:

    Book name/
        Book name.md              the whole book (or the index, with chapters)
        01 - First chapter.md     with "one note per chapter"
        images/book-name-p012-1.png

* text in reading order, paragraphs joined again, headings with their
  levels, running heads and page numbers left out;
* every drawing, photo and diagram cut out of its page and placed where it
  belongs, with its caption as description - line drawings as sharp PNG,
  photos as light JPEG;
* scanned pages read with the offline OCR;
* a YAML header on every note (title, author, source, pages...) and a mark
  where each page starts, so an answer can be traced back to its page.

Formats: PDF, EPUB, Word (DOCX), Writer (ODT), PowerPoint (PPTX), web pages
(HTML), Excel and CSV, pictures, text and Markdown.  Nothing is sent
anywhere and nothing here imports Qt.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import human_size
from promak.core.paths import safe_filename
from promak.tools.booknotes import formats
from promak.tools.booknotes.model import (
    Document,
    NotesError,
    NotesOptions,
    PictureSink,
    clear_old_notes,
    estimate_tokens,
    human_tokens,
    notes_folder,
    slug,
    write_notes,
)
from promak.tools.booknotes.pdf_reader import (
    PICTURES_FIGURES,
    PICTURES_NONE,
    PICTURES_PAGES,
    ReadSettings,
    read_pdf,
)

log = logging.getLogger(__name__)

PDF_EXTENSIONS = (".pdf",)
ACCEPTED_EXTENSIONS = tuple(dict.fromkeys(
    PDF_EXTENSIONS + formats.EPUB_EXTENSIONS + formats.WORD_EXTENSIONS + formats.ODT_EXTENSIONS
    + formats.SLIDE_EXTENSIONS + formats.HTML_EXTENSIONS + formats.SHEET_EXTENSIONS
    + formats.PICTURE_EXTENSIONS + formats.TEXT_EXTENSIONS))

PICTURE_CHOICES = [
    ("Drawings and pictures, cut out where they are (recommended)", PICTURES_FIGURES),
    ("Every page as a picture too (for very visual books)", PICTURES_PAGES),
    ("No pictures - text only", PICTURES_NONE),
]
SIZE_CHOICES = [
    ("Medium - 1600 px (recommended)", 1600),
    ("Small - 1000 px (lighter for AI)", 1000),
    ("Large - 2400 px (fine print in drawings)", 2400),
]
SPLIT_CHOICES = [
    ("One note per chapter, plus an index note", True),
    ("One note for the whole document", False),
]


@dataclass
class BookNotesOptions:
    split: bool = True               # one note per chapter
    pictures: str = PICTURES_FIGURES
    picture_size: int = 1600         # longest side of a saved picture, in pixels
    ocr: bool = True                 # read scanned pages and pictures
    page_marks: bool = True
    overwrite: bool = False

    def validate(self) -> Optional[str]:
        if self.pictures not in (PICTURES_FIGURES, PICTURES_PAGES, PICTURES_NONE):
            return "Choose what to do with the pictures."
        if not 300 <= int(self.picture_size) <= 6000:
            return "Choose a picture size."
        return None


def read_document(path: Path, sink: Optional[PictureSink], options: BookNotesOptions,
                  report=None, check_cancel=None) -> Document:
    """Any accepted file, read into a :class:`Document`."""
    report = report or (lambda p, d="": None)
    suffix = path.suffix.lower()
    if suffix in PDF_EXTENSIONS:
        settings = ReadSettings(pictures=options.pictures, ocr=options.ocr)
        return read_pdf(path, sink, settings, report, check_cancel)
    if suffix in formats.EPUB_EXTENSIONS:
        return formats.read_epub(path, sink, report)
    if suffix in formats.WORD_EXTENSIONS:
        return formats.read_docx(path, sink)
    if suffix in formats.ODT_EXTENSIONS:
        return formats.read_odt(path, sink)
    if suffix in formats.SLIDE_EXTENSIONS:
        return formats.read_pptx(path, sink)
    if suffix in formats.HTML_EXTENSIONS:
        return formats.read_html(path, sink)
    if suffix in formats.SHEET_EXTENSIONS:
        return formats.read_sheets(path)
    if suffix in formats.PICTURE_EXTENSIONS:
        return formats.read_picture(path, sink, options.ocr)
    if suffix in formats.TEXT_EXTENSIONS:
        return formats.read_plain(path)
    raise NotesError(f"{suffix.lstrip('.').upper() or 'This'} files cannot be read here.")


class BookNotesBatch(BatchEngine):
    """Every file in the queue becomes a folder of Markdown notes."""

    what = "document(s)"

    def __init__(self, options: BookNotesOptions, **kwargs) -> None:
        super().__init__(**kwargs)
        self.options = options

    def process_one(self, job: FileJob, report) -> None:
        source = job.source
        if source.suffix.lower() not in ACCEPTED_EXTENSIONS:
            raise NotesError(f"{source.suffix.lstrip('.').upper()} files cannot be read here.")
        base_name = safe_filename(source.stem, fallback="document", max_length=80)
        folder = notes_folder(job.destination, base_name, self.options.overwrite)
        existed = folder.exists()
        if existed:
            clear_old_notes(folder)
        sink = None
        if self.options.pictures != PICTURES_NONE:
            sink = PictureSink(folder / "images", slug(source.stem), max_side=self.options.picture_size)
        report(1, "reading")
        try:
            document = read_document(source, sink, self.options, report, self.check_cancel)
            self.check_cancel()
            report(99, "writing the notes")
            written = write_notes(document, folder, base_name, source,
                                  NotesOptions(split=self.options.split, page_marks=self.options.page_marks))
        except BaseException:
            # nothing half-made is left behind in a folder this run created
            if not existed:
                shutil.rmtree(folder, ignore_errors=True)
            raise
        self._done(job, document, folder, written, sink)

    def _done(self, job: FileJob, document: Document, folder: Path, written: List[Path],
              sink: Optional[PictureSink]) -> None:
        text = "".join(path.read_text(encoding="utf-8") for path in written)
        tokens = estimate_tokens(text)
        pictures = len(sink.saved) if sink is not None else 0
        size = sum(p.stat().st_size for p in written) + sum(p.stat().st_size for p in (sink.saved if sink else []))
        job.output = written[0]
        job.output_bytes = size
        parts = []
        if document.pages:
            unit = {"pptx": "slide(s)", "epub": "part(s)", "xlsx": "sheet(s)", "xlsm": "sheet(s)"}.get(document.kind, "page(s)")
            parts.append(f"{document.pages} {unit}")
        if len(written) > 1:
            parts.append(f"{len(written) - 1} chapter note(s)")
        parts.append(f"{pictures} picture(s)")
        parts.append(f"≈ {human_tokens(tokens)}")
        job.info["result"] = f"{human_size(size)}, ≈ {human_tokens(tokens)}"
        job.info["folder"] = str(folder)
        job.message = ", ".join(parts)
        for note in document.notes:
            self._log("warning", f"{job.display_name}: {note}")
        if not text.strip() or (document.notes and "no text found" in " ".join(document.notes) and not pictures):
            job.stage = FileStage.DONE
            job.message = "no text or pictures found"

    def describe_result(self, job: FileJob) -> str:
        folder = job.info.get("folder", "")
        return f"{Path(folder).name}/ - {job.message}" if folder else job.message or "done"
