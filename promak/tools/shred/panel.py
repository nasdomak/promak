"""The secure delete screen.

Left: what to delete and how many passes.  Middle: every file that will be
destroyed, listed before anything happens.  The button asks twice: a
question, then the word DELETE typed by hand.  The limits of overwriting
are written on the screen, not hidden in a manual.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from promak.core.imaging import human_size
from promak.tools.shred.engine import CONFIRM_WORD, PASSES, WARNING, ShredOptions, collect, describe, forbidden, shred
from promak.ui.plan_panel import PlanPanel, combo, make_table, select


class ShredPanel(PlanPanel):
    """Overwrite files with random data, then delete them - with a strong confirmation."""

    TOOL_ID = "shred"
    PAGE_TITLE = "Secure delete"
    PAGE_SUBTITLE = (
        "Writes random data over files before deleting them, so recovery programs cannot bring them "
        "back - for old documents, scans of IDs, exports you no longer need. There is no undo and "
        "no Recycle Bin: you will be asked twice."
    )
    PREVIEW_TITLE = "Files that will be destroyed"
    SCAN_LABEL = "List the files"
    APPLY_LABEL = "Delete for good"
    APPLY_DANGER = True

    def __init__(self, parent=None) -> None:
        self._files: List[Path] = []
        super().__init__(parent)
        self.show_notice(WARNING, "warning")

    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - What to delete for good")
        inner = QVBoxLayout(box)
        self.items = QListWidget()
        self.items.setObjectName("PlainList")
        self.items.setMinimumHeight(110)
        self.items.setMaximumHeight(170)
        inner.addWidget(self.items)
        row = QHBoxLayout()
        add_files = QPushButton("Add files...")
        add_files.clicked.connect(self._add_files)
        add_folder = QPushButton("Add a folder...")
        add_folder.clicked.connect(self._add_folder)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        for button in (add_files, add_folder, remove):
            row.addWidget(button, 1)
        inner.addLayout(row)
        hint = QLabel("A folder is emptied with everything inside it. The computer's own folders, whole drives "
                      "and your personal folders themselves are refused.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        inner.addWidget(hint)
        layout.addWidget(box)

        box = QGroupBox("2 - How")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.passes_combo = combo(PASSES)
        self.folders_check = QCheckBox("Also remove the emptied folders themselves")
        grid.addWidget(QLabel("Overwrite"), 0, 0)
        grid.addWidget(self.passes_combo, 0, 1)
        grid.addWidget(self.folders_check, 1, 0, 1, 2)
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        self.table = make_table(("File", "Size"), stretch=(0,))
        return self.table

    # ------------------------------------------------------------- items
    def item_paths(self) -> List[Path]:
        return [Path(self.items.item(i).text()) for i in range(self.items.count())]

    def add_items(self, paths) -> None:
        known = {self.items.item(i).text() for i in range(self.items.count())}
        for path in paths:
            path = Path(path)
            problem = forbidden(path)
            if problem:
                self.log("warning", problem)
                continue
            if str(path) not in known:
                self.items.addItem(str(path))
                known.add(str(path))
        self._files = []
        self._fill()

    def on_dropped(self, paths) -> None:
        self.add_items(paths)

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Files to delete for good", str(Path.home()))
        self.add_items(files)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder to empty for good", str(Path.home()))
        if folder:
            self.add_items([folder])

    def _remove(self) -> None:
        for item in self.items.selectedItems():
            self.items.takeItem(self.items.row(item))
        self._files = []
        self._fill()

    def current_options(self) -> ShredOptions:
        return ShredOptions(items=self.item_paths(), passes=int(self.passes_combo.currentData() or 1),
                            remove_folders=self.folders_check.isChecked())

    def load_settings(self) -> None:
        select(self.passes_combo, int(self.config.get("shred.passes", 1)))
        self.folders_check.setChecked(bool(self.config.get("shred.remove_folders", True)))

    def save_settings(self) -> None:
        self.config.update({"shred.passes": int(self.passes_combo.currentData() or 1),
                            "shred.remove_folders": self.folders_check.isChecked()})

    # ----------------------------------------------------------- listing
    def validate_scan(self) -> Optional[str]:
        return self.current_options().validate()

    def scan_task(self):
        items = self.item_paths()
        return lambda progress, log, cancel: collect(items)[0]

    def on_scanned(self, files) -> None:
        self._files = list(files or [])
        self._fill()

    def _fill(self) -> None:
        self.table.setRowCount(0)
        for file in self._files[:20000]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(str(file)))
            try:
                size = human_size(file.stat().st_size)
            except OSError:
                size = "?"
            self.table.setItem(row, 1, QTableWidgetItem(size))
        self.summary_label.setText(describe(self._files) + " will be destroyed." if self._files else "")
        self.apply_button.setText(f"Delete {len(self._files)} file(s) for good" if self._files else self.APPLY_LABEL)
        self.refresh_buttons()

    # ------------------------------------------------------------ acting
    def can_apply(self) -> bool:
        return bool(getattr(self, "_files", []))

    def confirm_apply(self) -> bool:
        problem = self.current_options().validate()
        if problem:
            QMessageBox.warning(self, self.PAGE_TITLE, problem)
            return False
        if not self.ask("Delete for good", f"Destroy {describe(self._files)}?\n\nThey will NOT go to the Recycle "
                                           "Bin and cannot be brought back.", default_yes=False):
            return False
        word, ok = QInputDialog.getText(self, "Last check", f"Type {CONFIRM_WORD} to destroy the files:")
        if not ok or word.strip() != CONFIRM_WORD:
            self.log("info", "Nothing was deleted.")
            return False
        return True

    def apply_task(self):
        options = self.current_options()
        return lambda progress, log, cancel: shred(options, progress, cancel, log)

    def on_applied(self, result) -> None:
        self.log("info", f"{result['done']} file(s), {human_size(result['bytes'])}, deleted for good; "
                         f"{result['failed']} could not be.")
        self.items.clear()
        self._files = []
        self._fill()

    def screenshot_sample(self, sandbox: Path) -> None:
        folder = sandbox / "Old tax papers"
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("ID card scan.jpg", "Bank statement 2019.pdf", "Payslips 2019.zip"):
            (folder / name).write_bytes(b"\0" * 250_000)
        self.add_items([folder])
        self.on_scanned(self.run_now(self.scan_task()))
