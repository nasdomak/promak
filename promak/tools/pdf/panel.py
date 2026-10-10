"""The PDF toolbox screen.

Queues, folders, drag and drop, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the options,
and only the ones the chosen job needs are shown.
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.pdf.engine import (
    ACCEPTED_EXTENSIONS,
    ACTIONS,
    COMPRESS,
    COMPRESS_LEVELS,
    DELETE,
    DPI_CHOICES,
    KEEP,
    MERGE,
    PICTURE_FORMATS,
    PICTURES,
    PROTECT,
    ROTATE,
    SPLIT,
    SPLIT_CHUNKS,
    SPLIT_EVERY_PAGE,
    SPLIT_MODES,
    SPLIT_RANGES,
    UNPROTECT,
    PdfBatch,
    PdfOptions,
    is_protected,
    page_count,
)
from promak.ui.file_panel import FileQueuePanel

ANGLES = [("90 degrees clockwise", 90), ("Upside down (180)", 180), ("90 degrees anticlockwise", 270)]

PAGE_HINTS = {
    KEEP: "Pages to keep, in the order you want them:  3,1,2,4-end",
    DELETE: "Pages to delete:  2,5-7",
    ROTATE: "Pages to turn (empty = every page):  1,3-4",
    SPLIT: "One file per range:  1-3,4-6,7-end",
}


class PdfPanel(FileQueuePanel):
    """PDF files (and pictures to merge) in; new PDFs or pictures out."""

    TOOL_ID = "pdf"
    PAGE_TITLE = "PDF toolbox"
    PAGE_SUBTITLE = (
        "Merges, splits, picks, deletes, turns and reorders pages; makes a PDF lighter; turns "
        "pictures into one PDF or pages into pictures; adds or removes a password. Everything "
        "happens on this computer and your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - PDF files (and pictures to merge)"
    FILES_HINT = "Drag your PDF files here.\nTo make one PDF from pictures, drag the pictures too."
    FILE_DIALOG_FILTER = ("PDF files and pictures (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS)
                          + ");;PDF files (*.pdf);;All files (*)")
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "PDF files"
    DESTINATION_BOX_TITLE = "2 - Where to save the new files"
    OPTIONS_BOX_TITLE = "3 - What to do"
    EXTRA_COLUMNS = ("Pages", "Result")
    START_LABEL = "Do it"
    COMPONENTS = ("pikepdf", "pypdfium2")
    REORDERABLE = True

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self.action_combo = self._combo(ACTIONS)
        self.split_combo = self._combo(SPLIT_MODES)
        self.pages_input = QLineEdit()
        self.chunk_spin = QSpinBox()
        self.chunk_spin.setRange(1, 10000)
        self.chunk_spin.setSuffix(" page(s) per file")
        self.angle_combo = self._combo(ANGLES)
        self.level_combo = self._combo([(label, index) for index, (label, _q, _s) in enumerate(COMPRESS_LEVELS)])
        self.format_combo = self._combo(PICTURE_FORMATS)
        self.dpi_combo = self._combo(DPI_CHOICES)
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        self.show_password = QCheckBox("Show")
        self.show_password.toggled.connect(
            lambda on: self.password_input.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("optional - the first file's name plus \"merged\"")
        self.overwrite_check = QCheckBox("Replace files with the same name")
        self.pages_hint = QLabel()
        self.pages_hint.setObjectName("HintLabel")
        self.pages_hint.setWordWrap(True)
        self.password_hint = QLabel()
        self.password_hint.setObjectName("HintLabel")
        self.password_hint.setWordWrap(True)

        self._rows: Dict[str, List[QWidget]] = {}
        rows = (
            ("Job", self.action_combo, "all"),
            ("Split", self.split_combo, "split"),
            ("Pages", self.pages_input, "pages"),
            ("", self.pages_hint, "pages"),
            ("Every", self.chunk_spin, "chunks"),
            ("Turn", self.angle_combo, "rotate"),
            ("How much", self.level_combo, "compress"),
            ("Pictures", self.format_combo, "pictures"),
            ("Sharpness", self.dpi_combo, "pictures"),
            ("File name", self.name_input, "merge"),
            ("Password", self.password_input, "all"),
            ("", self.show_password, "all"),
            ("", self.password_hint, "all"),
        )
        for index, (caption, widget, kind) in enumerate(rows):
            label = QLabel(caption)
            grid.addWidget(label, index, 0)
            grid.addWidget(widget, index, 1)
            self._rows.setdefault(kind, []).extend([label, widget])
        grid.addWidget(self.overwrite_check, len(rows), 0, 1, 2)

        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        self.split_combo.currentIndexChanged.connect(self._on_action_changed)

    @staticmethod
    def _combo(items) -> QComboBox:
        combo = QComboBox()
        for label, value in items:
            combo.addItem(label, value)
        return combo

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _on_action_changed(self, *_args) -> None:
        action = self.action_combo.currentData() or MERGE
        split_mode = self.split_combo.currentData() or SPLIT_EVERY_PAGE
        wants_pages = action in (KEEP, DELETE, ROTATE) or (action == SPLIT and split_mode == SPLIT_RANGES)
        visible = {
            "all": True,
            "split": action == SPLIT,
            "pages": wants_pages,
            "chunks": action == SPLIT and split_mode == SPLIT_CHUNKS,
            "rotate": action == ROTATE,
            "compress": action == COMPRESS,
            "pictures": action == PICTURES,
            "merge": action == MERGE,
        }
        for kind, widgets in self._rows.items():
            for widget in widgets:
                widget.setVisible(visible.get(kind, True))
        hint = PAGE_HINTS.get(action, "")
        self.pages_hint.setText(hint + '\n"end" means the last page; 5-1 gives pages 5 to 1 backwards.')
        self.pages_input.setPlaceholderText(hint.split(":")[-1].strip())
        self.password_hint.setText({
            PROTECT: "The new copy will ask for this password before opening (AES-256). "
                     "Keep it somewhere safe: it cannot be recovered.",
            UNPROTECT: "Type the current password: the copy will open without one. "
                       "A PDF whose password you do not know cannot be unlocked.",
        }.get(action, "Only needed when a PDF in the queue asks for a password to open."))

    # ----------------------------------------------------------- settings
    def current_options(self) -> PdfOptions:
        return PdfOptions(
            action=self.action_combo.currentData() or MERGE,
            pages=self.pages_input.text(),
            split_mode=self.split_combo.currentData() or SPLIT_EVERY_PAGE,
            chunk=self.chunk_spin.value(),
            angle=int(self.angle_combo.currentData() or 90),
            level=int(self.level_combo.currentData() or 0),
            picture_format=self.format_combo.currentData() or "PNG",
            dpi=int(self.dpi_combo.currentData() or 150),
            password=self.password_input.text(),
            merged_name=self.name_input.text(),
            overwrite=self.overwrite_check.isChecked(),
        )

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        self._select(self.action_combo, c.get("pdf.action", MERGE))
        self._select(self.split_combo, c.get("pdf.split_mode", SPLIT_EVERY_PAGE))
        self.chunk_spin.setValue(int(c.get("pdf.chunk", 2)))
        self._select(self.angle_combo, int(c.get("pdf.angle", 90)))
        self._select(self.level_combo, int(c.get("pdf.level", 1)))
        self._select(self.format_combo, c.get("pdf.picture_format", "PNG"))
        self._select(self.dpi_combo, int(c.get("pdf.dpi", 150)))
        self.overwrite_check.setChecked(bool(c.get("pdf.overwrite", False)))
        self._on_action_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        # the pages and the password belong to one job, so they are not kept
        self.config.update({
            "pdf.action": o.action, "pdf.split_mode": o.split_mode, "pdf.chunk": o.chunk,
            "pdf.angle": o.angle, "pdf.level": o.level, "pdf.picture_format": o.picture_format,
            "pdf.dpi": o.dpi, "pdf.overwrite": o.overwrite,
        })

    # ------------------------------------------------------------ running
    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return PdfBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        options = self.current_options()
        problem = options.validate()
        if problem:
            return problem
        if options.action != MERGE and not any(job.source.suffix.lower() == ".pdf" for job in self._jobs):
            return "The queue holds only pictures: choose \"Merge into one PDF\" to make a PDF of them."
        return None

    def extra_values(self, job: FileJob) -> Sequence[str]:
        if "pages" not in job.info and job.source.suffix.lower() == ".pdf":
            # counted once, when the file joins the queue
            try:
                job.info["pages"] = str(page_count(job.source))
            except Exception:  # protected or damaged: the run will say why
                job.info["pages"] = "locked" if is_protected(job.source) else "?"
        return (job.info.get("pages", ""), job.info.get("result", ""))
