"""The document converter screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the choice
of format and the few options that go with it.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel, QLineEdit

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.docconvert.engine import (
    ACCEPTED_EXTENSIONS,
    DELIMITERS,
    NO_OFFICE_MESSAGE,
    SOURCES,
    TARGETS,
    TO_CSV,
    TO_PDF,
    TO_TXT,
    ConvertBatch,
    ConvertOptions,
    office_pdf_converter,
)
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import combo, select


class DocConvertPanel(FileQueuePanel):
    """Word, Markdown, text, Excel and CSV files in; the chosen format out."""

    TOOL_ID = "docconvert"
    PAGE_TITLE = "Convert documents"
    PAGE_SUBTITLE = (
        "Turns Word files into text, Markdown or web pages and back, Excel sheets into CSV and back, "
        "and Office files into PDF. Headings, lists, bold, italic and tables are kept. Your "
        "originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Documents"
    FILES_HINT = "Drag your documents here.\nDOCX, MD, TXT, XLSX, CSV - and for PDF also DOC, ODT, XLS, PPTX..."
    FILE_DIALOG_FILTER = ("Documents (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS) + ");;All files (*)")
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "documents"
    DESTINATION_BOX_TITLE = "2 - Where to save the converted files"
    OPTIONS_BOX_TITLE = "3 - Convert to"
    EXTRA_COLUMNS = ("Result",)
    START_LABEL = "Convert"
    COMPONENTS = ("docx", "openpyxl")

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.target_combo = combo(TARGETS)
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        self.delimiter_combo = combo(DELIMITERS)
        self.sheets_check = QCheckBox("Every sheet as its own CSV (otherwise only the first)")
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("optional, for example  -converted")
        self.overwrite_check = QCheckBox("Replace files with the same name")
        self.sources_label = QLabel()
        self.sources_label.setObjectName("HintLabel")
        self.sources_label.setWordWrap(True)
        self.delimiter_caption = QLabel("Separator")
        grid.addWidget(QLabel("Format"), 0, 0)
        grid.addWidget(self.target_combo, 0, 1)
        grid.addWidget(self.sources_label, 1, 0, 1, 2)
        grid.addWidget(self.delimiter_caption, 2, 0)
        grid.addWidget(self.delimiter_combo, 2, 1)
        grid.addWidget(self.sheets_check, 3, 0, 1, 2)
        grid.addWidget(QLabel("Add to names"), 4, 0)
        grid.addWidget(self.suffix_input, 4, 1)
        grid.addWidget(self.overwrite_check, 5, 0, 1, 2)
        note = QLabel("Pictures inside a Word file are not carried over to text, Markdown or HTML.")
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        grid.addWidget(note, 6, 0, 1, 2)

    def _on_target_changed(self, *_args) -> None:
        target = self.target_combo.currentData() or TO_TXT
        for widget in (self.delimiter_caption, self.delimiter_combo, self.sheets_check):
            widget.setVisible(target == TO_CSV)
        sources = ", ".join(e.lstrip(".").upper() for e in SOURCES[target])
        text = f"Takes: {sources}."
        if target == TO_PDF:
            converter = office_pdf_converter()
            text += f"  Pages drawn by {converter}." if converter else "  " + NO_OFFICE_MESSAGE
            self.show_notice("" if converter else NO_OFFICE_MESSAGE, "warning")
        else:
            self.show_notice(self.missing_components_message(), "warning")
        self.sources_label.setText(text)

    def current_options(self) -> ConvertOptions:
        return ConvertOptions(target=self.target_combo.currentData() or TO_TXT,
                              every_sheet=self.sheets_check.isChecked(),
                              delimiter=self.delimiter_combo.currentData() or ",",
                              suffix=self.suffix_input.text(), overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        select(self.target_combo, c.get("docconvert.target", TO_TXT))
        select(self.delimiter_combo, c.get("docconvert.delimiter", ","))
        self.sheets_check.setChecked(bool(c.get("docconvert.every_sheet", True)))
        self.suffix_input.setText(c.get("docconvert.suffix", "") or "")
        self.overwrite_check.setChecked(bool(c.get("docconvert.overwrite", False)))
        self._on_target_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"docconvert.target": o.target, "docconvert.delimiter": o.delimiter,
                            "docconvert.every_sheet": o.every_sheet, "docconvert.suffix": o.suffix,
                            "docconvert.overwrite": o.overwrite})

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return ConvertBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        options = self.current_options()
        problem = options.validate()
        if problem:
            return problem
        if not any(job.source.suffix.lower() in SOURCES[options.target] for job in self._jobs
                   if not job.stage.is_final):
            sources = ", ".join(e.lstrip(".").upper() for e in SOURCES[options.target])
            return f"No file in the queue can become {options.target.upper()}: that needs {sources}."
        return None

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (job.info.get("result", ""),)
