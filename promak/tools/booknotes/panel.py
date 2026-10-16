"""The Books to Markdown screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is how the notes
are cut (chapters or one note), what happens to the pictures, the OCR and
the words to remove.
"""

from __future__ import annotations

import importlib.util
import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.booknotes.engine import (
    ACCEPTED_EXTENSIONS,
    PICTURE_CHOICES,
    PICTURES_NONE,
    SIZE_CHOICES,
    SPLIT_CHOICES,
    BookNotesBatch,
    BookNotesOptions,
)
from promak.tools.booknotes.pdf_reader import PICTURES_FIGURES
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import combo, select
from promak.ui.word_filter_box import WordFilterBox

OCR_MISSING = ("The OCR engine is missing, so scanned pages and photos of pages are kept as pictures "
               "without their text. Run install_windows.bat again, or:  pip install -U rapidocr onnxruntime")


def ocr_available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("rapidocr", "onnxruntime"))


class BookNotesPanel(FileQueuePanel):
    """Books and documents in; a folder of Markdown notes with pictures out."""

    TOOL_ID = "booknotes"
    PAGE_TITLE = "Books to Markdown"
    PAGE_SUBTITLE = (
        "Turns heavy books and documents into light Markdown notes for an AI or a second brain "
        "(Obsidian, Logseq...): text in reading order, headings, one note per chapter, every drawing "
        "and photo cut out where it belongs, scanned pages read with the offline OCR. Nothing leaves "
        "this computer and your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Books and documents"
    FILES_HINT = ("Drag your books here.\nPDF (also scanned), EPUB, DOCX, ODT, PPTX, HTML, XLSX, CSV, "
                  "pictures of pages, TXT, MD")
    FILE_DIALOG_FILTER = ("Books and documents (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS)
                          + ");;All files (*)")
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "documents"
    DESTINATION_BOX_TITLE = "2 - Where to save the notes"
    OPTIONS_BOX_TITLE = "3 - How the notes are made"
    EXTRA_COLUMNS = ("Result",)
    EXTRA_COLUMN_WIDTH = 120
    START_LABEL = "Make the notes"
    COMPONENTS = ("pypdfium2",)

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.split_combo = combo(SPLIT_CHOICES)
        self.pictures_combo = combo(PICTURE_CHOICES)
        self.pictures_combo.currentIndexChanged.connect(self._on_options_changed)
        self.size_combo = combo(SIZE_CHOICES)
        self.ocr_check = QCheckBox("Read scanned pages and photos of pages (offline OCR)")
        self.ocr_check.setToolTip("A page that is only a picture of paper is read word by word on this computer.\n"
                                  "Slower: a few seconds a page. The drawings on a scan are cut out too.")
        self.ocr_check.toggled.connect(self._on_options_changed)
        self.marks_check = QCheckBox("Mark where each page starts (to find the source of an answer)")
        self.overwrite_check = QCheckBox("Replace notes made before for the same file")
        self.word_filter_box = WordFilterBox("Remove these words from the notes")
        self.hint = QLabel()
        self.hint.setObjectName("HintLabel")
        self.hint.setWordWrap(True)
        rows = (("Notes", self.split_combo), ("Pictures", self.pictures_combo), ("Picture size", self.size_combo))
        for index, (caption, widget) in enumerate(rows):
            grid.addWidget(QLabel(caption), index, 0)
            grid.addWidget(widget, index, 1)
        row = len(rows)
        for widget in (self.ocr_check, self.marks_check, self.overwrite_check, self.word_filter_box, self.hint):
            grid.addWidget(widget, row, 0, 1, 2)
            row += 1

    def _on_options_changed(self, *_args) -> None:
        pictures = self.pictures_combo.currentData() or PICTURES_FIGURES
        self.size_combo.setEnabled(pictures != PICTURES_NONE)
        messages = []
        if pictures != PICTURES_NONE:
            messages.append("Pictures go in an \"images\" folder next to the notes; drawings are kept as sharp "
                            "PNG, photos as light JPEG.")
        messages.append("Each note starts with a small header (title, author, source, pages) an AI or "
                        "Obsidian can read.")
        self.hint.setText("  ".join(messages))
        missing = self.missing_components_message()
        if not missing and self.ocr_check.isChecked() and not ocr_available():
            missing = OCR_MISSING
        self.show_notice(missing, "warning")

    def current_options(self) -> BookNotesOptions:
        return BookNotesOptions(split=bool(self.split_combo.currentData()),
                                pictures=self.pictures_combo.currentData() or PICTURES_FIGURES,
                                picture_size=int(self.size_combo.currentData() or 1600),
                                ocr=self.ocr_check.isChecked(), page_marks=self.marks_check.isChecked(),
                                overwrite=self.overwrite_check.isChecked(),
                                drop_words=self.word_filter_box.phrases_text(),
                                drop_match_case=self.word_filter_box.match_case())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        select(self.split_combo, bool(c.get("booknotes.split", True)))
        select(self.pictures_combo, c.get("booknotes.pictures", PICTURES_FIGURES))
        select(self.size_combo, int(c.get("booknotes.picture_size", 1600)))
        self.ocr_check.setChecked(bool(c.get("booknotes.ocr", True)))
        self.marks_check.setChecked(bool(c.get("booknotes.page_marks", True)))
        self.overwrite_check.setChecked(bool(c.get("booknotes.overwrite", False)))
        self.word_filter_box.load(c)
        self._on_options_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"booknotes.split": o.split, "booknotes.pictures": o.pictures,
                            "booknotes.picture_size": o.picture_size, "booknotes.ocr": o.ocr,
                            "booknotes.page_marks": o.page_marks, "booknotes.overwrite": o.overwrite})
        self.word_filter_box.save(self.config)

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return BookNotesBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        return self.current_options().validate() or self.word_filter_box.problem() or None

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (job.info.get("result", ""),)
