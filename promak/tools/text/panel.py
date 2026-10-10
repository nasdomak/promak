"""The text toolbox screen.

Queues, folders, drag and drop, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the options
and a preview of the result.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
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
from promak.tools.text.engine import (
    FORMAT_CHOICES,
    MAKE_CHOICES,
    MAKE_CLEAN,
    SUMMARY_SIZES,
    TEXT_EXTENSIONS,
    TextBatch,
    TextOptions,
)
from promak.ui.file_panel import FileQueuePanel


class TextPanel(FileQueuePanel):
    """Messy text in; clean text, summaries or other formats out."""

    TOOL_ID = "text"
    PAGE_TITLE = "Text toolbox"
    PAGE_SUBTITLE = (
        "Tidies up text copied from PDFs, e-mails and web pages, turns subtitles and "
        "transcripts into readable paragraphs, writes a short summary made of the text's own key "
        "sentences, and saves it as plain text, Markdown or a web page. Everything happens on "
        "this computer: no text is sent anywhere."
    )
    FILES_BOX_TITLE = "1 - Text files"
    FILES_HINT = "Drag your text files here.\nTXT, MD, SRT and VTT subtitles, HTML, CSV..."
    FILE_DIALOG_FILTER = "Text (" + " ".join(f"*{e}" for e in TEXT_EXTENSIONS) + ");;All files (*)"
    ACCEPTED_EXTENSIONS: Sequence[str] = TEXT_EXTENSIONS
    ITEM_WORD = "text files"
    DESTINATION_BOX_TITLE = "2 - Where to save the new files"
    OPTIONS_BOX_TITLE = "3 - What to make"
    EXTRA_COLUMNS = ("Result",)
    START_LABEL = "Do it"

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.make_combo = QComboBox()
        for label, value in MAKE_CHOICES:
            self.make_combo.addItem(label, value)
        self.size_combo = QComboBox()
        for label, value in SUMMARY_SIZES:
            self.size_combo.addItem(label, value)
        self.format_combo = QComboBox()
        for label, value in FORMAT_CHOICES:
            self.format_combo.addItem(label, value)
        self.join_check = QCheckBox("Join lines broken in the middle of a sentence")
        self.join_check.setToolTip("Text copied from a PDF breaks every line at the page edge; this rejoins them.")
        self.quotes_check = QCheckBox("Straight quotes and dashes  (“ ” – become \" -)")
        self.duplicates_check = QCheckBox("Remove repeated lines")
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("optional, for example  -clean")
        self.overwrite_check = QCheckBox("Redo files that already exist")
        rows = (("Make", self.make_combo), ("Summary", self.size_combo), ("Format", self.format_combo),
                ("Add to names", self.suffix_input))
        for index, (caption, widget) in enumerate(rows):
            grid.addWidget(QLabel(caption), index, 0)
            grid.addWidget(widget, index, 1)
        for offset, check in enumerate((self.join_check, self.quotes_check, self.duplicates_check,
                                        self.overwrite_check)):
            grid.addWidget(check, len(rows) + offset, 0, 1, 2)
        self.make_combo.currentIndexChanged.connect(self._on_make_changed)

    def build_extra_area(self) -> Optional[QWidget]:
        box = QGroupBox("Result")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 6, 12, 10)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setPlaceholderText("Select a finished row to read the result here.")
        self.preview.setMinimumHeight(180)
        layout.addWidget(self.preview)
        return box

    def _on_make_changed(self, *_args) -> None:
        self.size_combo.setEnabled((self.make_combo.currentData() or MAKE_CLEAN) != MAKE_CLEAN)

    def current_options(self) -> TextOptions:
        return TextOptions(
            make=self.make_combo.currentData() or MAKE_CLEAN,
            output_format=self.format_combo.currentData() or "txt",
            join_broken_lines=self.join_check.isChecked(),
            straight_quotes=self.quotes_check.isChecked(),
            remove_duplicate_lines=self.duplicates_check.isChecked(),
            summary_size=int(self.size_combo.currentData() or 10),
            suffix=self.suffix_input.text(),
            overwrite=self.overwrite_check.isChecked(),
        )

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        self._select(self.make_combo, c.get("text.make", MAKE_CLEAN))
        self._select(self.size_combo, int(c.get("text.summary_size", 10)))
        self._select(self.format_combo, c.get("text.format", "txt"))
        self.join_check.setChecked(bool(c.get("text.join", True)))
        self.quotes_check.setChecked(bool(c.get("text.quotes", False)))
        self.duplicates_check.setChecked(bool(c.get("text.duplicates", False)))
        self.suffix_input.setText(c.get("text.suffix", "") or "")
        self.overwrite_check.setChecked(bool(c.get("text.overwrite", False)))
        self._on_make_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({
            "text.make": o.make, "text.summary_size": o.summary_size, "text.format": o.output_format,
            "text.join": o.join_broken_lines, "text.quotes": o.straight_quotes,
            "text.duplicates": o.remove_duplicate_lines, "text.suffix": o.suffix,
            "text.overwrite": o.overwrite,
        })

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return TextBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (job.info.get("result", ""),)

    def on_job_selected(self, job: Optional[FileJob]) -> None:
        self._show(job)

    def on_job_finished(self, job: FileJob) -> None:
        selected = self._selected_jobs()
        if not selected or selected[0].id == job.id:
            self._show(job)

    def _show(self, job: Optional[FileJob]) -> None:
        if job is None or not job.output or not Path(job.output).is_file():
            self.preview.clear()
            return
        try:
            self.preview.setPlainText(Path(job.output).read_text(encoding="utf-8")[:20000])
        except OSError:
            self.preview.clear()
