"""The "text from pictures" (OCR) screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the options
and a box that shows the text read from the selected file.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.ocr.engine import (
    ACCEPTED_EXTENSIONS,
    DPI_CHOICES,
    LANGUAGES_TEXT,
    MAKE_TEXT,
    MAKES,
    OcrBatch,
    OcrOptions,
)
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import combo, select


class OcrPanel(FileQueuePanel):
    """Pictures and scanned PDFs in; text files or searchable PDFs out."""

    TOOL_ID = "ocr"
    PAGE_TITLE = "Text from pictures (OCR)"
    PAGE_SUBTITLE = (
        "Reads the text in photos of documents, screenshots and scanned PDFs, and saves it as a "
        "text file or as a PDF you can search and copy from. It works offline: nothing is "
        "uploaded and nothing has to be installed by hand."
    )
    FILES_BOX_TITLE = "1 - Pictures and scanned PDFs"
    FILES_HINT = "Drag your scans, photos of documents or screenshots here.\nJPG, PNG, TIFF, WEBP and PDF."
    FILE_DIALOG_FILTER = ("Pictures and PDFs (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS)
                          + ");;All files (*)")
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "pictures or PDFs"
    DESTINATION_BOX_TITLE = "2 - Where to save the text"
    OPTIONS_BOX_TITLE = "3 - What to make"
    EXTRA_COLUMNS = ("Pages", "Words")
    START_LABEL = "Read the text"
    RUNNING_LABEL = "Reading..."
    COMPONENTS = ("rapidocr", "onnxruntime", "pikepdf", "pypdfium2")

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.make_combo = combo(MAKES)
        self.dpi_combo = combo(DPI_CHOICES)
        self.dpi_combo.setToolTip("How finely the pages of a PDF are looked at. Small print reads better at 300 dpi.")
        self.skip_check = QCheckBox("Leave alone PDF pages that already hold text")
        self.skip_check.setToolTip("Their text is copied as it is; only the scanned pages are read.")
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("optional, for example  -ocr")
        self.overwrite_check = QCheckBox("Replace files with the same name")
        languages = QLabel(LANGUAGES_TEXT)
        languages.setObjectName("HintLabel")
        languages.setWordWrap(True)
        grid.addWidget(QLabel("Make"), 0, 0)
        grid.addWidget(self.make_combo, 0, 1)
        grid.addWidget(QLabel("PDF pages"), 1, 0)
        grid.addWidget(self.dpi_combo, 1, 1)
        grid.addWidget(self.skip_check, 2, 0, 1, 2)
        grid.addWidget(QLabel("Add to names"), 3, 0)
        grid.addWidget(self.suffix_input, 3, 1)
        grid.addWidget(self.overwrite_check, 4, 0, 1, 2)
        grid.addWidget(languages, 5, 0, 1, 2)

    def build_extra_area(self) -> Optional[QWidget]:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        label = QLabel("Text read")
        label.setObjectName("SectionLabel")
        self.text_view = QPlainTextEdit()
        self.text_view.setReadOnly(True)
        self.text_view.setPlaceholderText("Select a finished file to see its text here.")
        self.text_view.setMinimumHeight(220)
        layout.addWidget(label)
        layout.addWidget(self.text_view)
        return holder

    # ----------------------------------------------------------- settings
    def current_options(self) -> OcrOptions:
        return OcrOptions(make=self.make_combo.currentData() or MAKE_TEXT, dpi=int(self.dpi_combo.currentData() or 200),
                          skip_text_pages=self.skip_check.isChecked(), suffix=self.suffix_input.text(),
                          overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        select(self.make_combo, c.get("ocr.make", MAKE_TEXT))
        select(self.dpi_combo, int(c.get("ocr.dpi", 200)))
        self.skip_check.setChecked(bool(c.get("ocr.skip_text_pages", True)))
        self.suffix_input.setText(c.get("ocr.suffix", "") or "")
        self.overwrite_check.setChecked(bool(c.get("ocr.overwrite", False)))

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"ocr.make": o.make, "ocr.dpi": o.dpi, "ocr.skip_text_pages": o.skip_text_pages,
                            "ocr.suffix": o.suffix, "ocr.overwrite": o.overwrite})

    # ------------------------------------------------------------ running
    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return OcrBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (job.info.get("pages", ""), job.info.get("words", ""))

    def on_job_selected(self, job: Optional[FileJob]) -> None:
        self._show_text(job)

    def on_job_finished(self, job: FileJob) -> None:
        self._show_text(job)

    def _show_text(self, job: Optional[FileJob]) -> None:
        if job is None or job.output is None:
            self.text_view.setPlainText("")
            return
        text_file = job.output if job.output.suffix.lower() == ".txt" else None
        if text_file is None or not text_file.exists():
            self.text_view.setPlainText(f"Saved as {job.output.name}.")
            return
        try:
            self.text_view.setPlainText(text_file.read_text(encoding="utf-8")[:20000])
        except OSError as exc:
            self.text_view.setPlainText(f"The text cannot be shown: {exc}")
