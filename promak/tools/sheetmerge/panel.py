"""The "merge spreadsheets" screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the options.
The order of the queue is the order of the rows in the result.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel, QLineEdit

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.sheetmerge.engine import ACCEPTED_EXTENSIONS, FORMATS, MergeOptions, SheetMergeBatch
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import combo, select


class SheetMergePanel(FileQueuePanel):
    """Many CSV and Excel files in; one table out."""

    TOOL_ID = "sheetmerge"
    PAGE_TITLE = "Merge spreadsheets"
    PAGE_SUBTITLE = (
        "Puts the rows of many CSV and Excel files into one table. Columns are matched by their "
        "name, not their place, a column says which file each row came from, and repeated rows "
        "can be dropped. Your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Spreadsheets (in the order the rows should come)"
    FILES_HINT = "Drag your CSV and Excel files here.\nThe first row of each sheet holds the column names."
    FILE_DIALOG_FILTER = "Spreadsheets (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS) + ");;All files (*)"
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "spreadsheets"
    DESTINATION_BOX_TITLE = "2 - Where to save the merged file"
    OPTIONS_BOX_TITLE = "3 - How to merge"
    EXTRA_COLUMNS = ("Rows",)
    START_LABEL = "Merge"
    COMPONENTS = ("openpyxl",)
    REORDERABLE = True

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.format_combo = combo(FORMATS)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("optional - the first file's name plus \"merged\"")
        self.source_check = QCheckBox('Add a "Source file" column')
        self.duplicates_check = QCheckBox("Drop rows that appear more than once")
        self.sheets_check = QCheckBox("Every sheet of a workbook, not only the first")
        self.overwrite_check = QCheckBox("Replace a file with the same name")
        hint = QLabel("Columns with the same name are put together even when they are in a different place "
                      "(\"amount\" and \"Amount\" too); a column only some files have is left empty for the others.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        grid.addWidget(QLabel("Save as"), 0, 0)
        grid.addWidget(self.format_combo, 0, 1)
        grid.addWidget(QLabel("File name"), 1, 0)
        grid.addWidget(self.name_input, 1, 1)
        grid.addWidget(self.source_check, 2, 0, 1, 2)
        grid.addWidget(self.duplicates_check, 3, 0, 1, 2)
        grid.addWidget(self.sheets_check, 4, 0, 1, 2)
        grid.addWidget(self.overwrite_check, 5, 0, 1, 2)
        grid.addWidget(hint, 6, 0, 1, 2)

    def current_options(self) -> MergeOptions:
        return MergeOptions(every_sheet=self.sheets_check.isChecked(), source_column=self.source_check.isChecked(),
                            drop_duplicates=self.duplicates_check.isChecked(),
                            output_format=self.format_combo.currentData() or "xlsx",
                            name=self.name_input.text(), overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        select(self.format_combo, c.get("sheetmerge.format", "xlsx"))
        self.source_check.setChecked(bool(c.get("sheetmerge.source_column", True)))
        self.duplicates_check.setChecked(bool(c.get("sheetmerge.drop_duplicates", False)))
        self.sheets_check.setChecked(bool(c.get("sheetmerge.every_sheet", False)))
        self.overwrite_check.setChecked(bool(c.get("sheetmerge.overwrite", False)))

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"sheetmerge.format": o.output_format, "sheetmerge.source_column": o.source_column,
                            "sheetmerge.drop_duplicates": o.drop_duplicates, "sheetmerge.every_sheet": o.every_sheet,
                            "sheetmerge.overwrite": o.overwrite})

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return SheetMergeBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (job.info.get("rows", ""),)
