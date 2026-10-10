"""The "compare two folders" screen.

Left: the two folders and how to compare them.  Middle: every file with its
answer - only on the left, only on the right, different, identical - and a
filter.  The missing files can then be copied across, after a question.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtGui import QColor
from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from promak.core.fileops import forget_journal, load_journal, undo_journal
from promak.core.imaging import human_size
from promak.tools.compare.engine import (
    BOTH_WAYS,
    DIFFERENT,
    DIRECTIONS,
    IDENTICAL,
    LEFT_TO_RIGHT,
    ONLY_LEFT,
    ONLY_RIGHT,
    TOOL,
    CompareOptions,
    Difference,
    compare_folders,
    copy_missing,
    copy_plan,
    summary_text,
)
from promak.ui.plan_panel import PlanPanel, combo, folder_field, make_table, select
from promak.ui.theme import palette

SHOW = [("Every file", "all"), ("Only the differences", "diff"), ("Only on the left", ONLY_LEFT),
        ("Only on the right", ONLY_RIGHT), ("Different", DIFFERENT), ("Identical", IDENTICAL)]


class ComparePanel(PlanPanel):
    """Two folders side by side: what is missing, what differs, what is the same."""

    TOOL_ID = "compare"
    PAGE_TITLE = "Compare two folders"
    PAGE_SUBTITLE = (
        "Shows which files are only in one of two folders, which differ and which are identical - "
        "for example a folder and its backup - and copies across the files one side is missing. "
        "Nothing is ever overwritten or deleted, and the last copy can be undone."
    )
    PREVIEW_TITLE = "Files"
    SCAN_LABEL = "Compare"
    APPLY_LABEL = "Copy the missing files"
    UNDO_LABEL = "Undo last copy"

    def __init__(self, parent=None) -> None:
        self._results: List[Difference] = []
        super().__init__(parent)

    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - The two folders")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        left, self.left_input = folder_field("For example  D:\\Photos", "Left folder")
        right, self.right_input = folder_field("For example  E:\\Backup\\Photos", "Right folder")
        grid.addWidget(QLabel("Left"), 0, 0)
        grid.addWidget(left, 0, 1)
        grid.addWidget(QLabel("Right"), 1, 0)
        grid.addWidget(right, 1, 1)
        hint = QLabel("Drag a folder onto the screen: the first goes left, the second right.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        grid.addWidget(hint, 2, 0, 1, 2)
        layout.addWidget(box)

        box = QGroupBox("2 - How to compare")
        inner = QVBoxLayout(box)
        self.recursive_check = QCheckBox("Also the sub-folders")
        self.quick_check = QCheckBox("Quick: same size and date counts as identical (no reading)")
        self.quick_check.setToolTip("Without it every pair of files with the same size is read and compared, "
                                    "which is exact but takes longer on big folders.")
        self.hidden_check = QCheckBox("Include hidden files")
        for widget in (self.recursive_check, self.quick_check, self.hidden_check):
            inner.addWidget(widget)
        layout.addWidget(box)

        box = QGroupBox("3 - Copy what is missing")
        grid = QGridLayout(box)
        grid.setColumnStretch(0, 1)
        self.direction_combo = combo(DIRECTIONS)
        self.direction_combo.currentIndexChanged.connect(self._refresh_summary)
        note = QLabel("Only missing files are copied, with their dates. Files that differ are shown but left "
                      "as they are: decide yourself which one to keep.")
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        grid.addWidget(self.direction_combo, 0, 0)
        grid.addWidget(note, 1, 0)
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        self.show_combo = combo(SHOW)
        self.show_combo.currentIndexChanged.connect(self._fill)
        layout.addWidget(self.show_combo)
        self.table = make_table(("File", "Answer", "Left", "Right"), stretch=(0,))
        self.table.setColumnWidth(1, 130)
        self.table.setColumnWidth(2, 160)
        self.table.setColumnWidth(3, 160)
        layout.addWidget(self.table, 1)
        return holder

    def current_options(self) -> CompareOptions:
        left, right = self.left_input.text().strip(), self.right_input.text().strip()
        return CompareOptions(left=Path(left) if left else None, right=Path(right) if right else None,
                              recursive=self.recursive_check.isChecked(), quick=self.quick_check.isChecked(),
                              include_hidden=self.hidden_check.isChecked())

    def load_settings(self) -> None:
        c = self.config
        self.left_input.setText(c.get("compare.left", "") or "")
        self.right_input.setText(c.get("compare.right", "") or "")
        self.recursive_check.setChecked(bool(c.get("compare.recursive", True)))
        self.quick_check.setChecked(bool(c.get("compare.quick", False)))
        select(self.direction_combo, c.get("compare.direction", LEFT_TO_RIGHT))
        select(self.show_combo, c.get("compare.show", "diff"))

    def save_settings(self) -> None:
        o = self.current_options()
        self.config.update({"compare.left": str(o.left or ""), "compare.right": str(o.right or ""),
                            "compare.recursive": o.recursive, "compare.quick": o.quick,
                            "compare.direction": self.direction_combo.currentData(),
                            "compare.show": self.show_combo.currentData()})

    def on_dropped(self, paths) -> None:
        for path in paths:
            folder = path if path.is_dir() else path.parent
            if not self.left_input.text().strip() or self.right_input.text().strip():
                self.left_input.setText(str(folder))
                self.right_input.setText("")
            else:
                self.right_input.setText(str(folder))

    # ------------------------------------------------------------ compare
    def validate_scan(self) -> Optional[str]:
        return self.current_options().validate()

    def scan_task(self):
        options = self.current_options()
        return lambda progress, log, cancel: compare_folders(options, progress, cancel)

    def on_scanned(self, results) -> None:
        self._results = list(results or [])
        self.log("info", summary_text(self._results))
        self._fill()

    def _fill(self, *_args) -> None:
        show = self.show_combo.currentData() or "all"
        colours = palette(self.config.get("app.theme", "light"))
        tint = {ONLY_LEFT: colours["accent"], ONLY_RIGHT: colours["accent"], DIFFERENT: colours["warning"],
                IDENTICAL: colours["success"]}
        self.table.setRowCount(0)
        for item in self._results:
            if show == "diff" and item.status == IDENTICAL:
                continue
            if show not in ("all", "diff") and item.status != show:
                continue
            if self.table.rowCount() >= 20000:
                break
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = QTableWidgetItem(item.relative)
            name.setToolTip(item.relative)
            answer = QTableWidgetItem(item.status + (f" ({item.newer})" if item.newer else ""))
            answer.setForeground(QColor(tint[item.status]))
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, answer)
            self.table.setItem(row, 2, QTableWidgetItem(item.left.text if item.left else "-"))
            self.table.setItem(row, 3, QTableWidgetItem(item.right.text if item.right else "-"))
        self._refresh_summary()

    def _refresh_summary(self, *_args) -> None:
        plan = copy_plan(self._results, self.direction_combo.currentData() or LEFT_TO_RIGHT)
        self.summary_label.setText(summary_text(self._results) if self._results else "")
        self.apply_button.setText(f"Copy {len(plan)} missing file(s)" if plan else self.APPLY_LABEL)
        self.refresh_buttons()

    # --------------------------------------------------------------- copy
    def can_apply(self) -> bool:
        return bool(copy_plan(getattr(self, "_results", []), self.direction_combo.currentData() or LEFT_TO_RIGHT))

    def confirm_apply(self) -> bool:
        direction = self.direction_combo.currentData() or LEFT_TO_RIGHT
        plan = copy_plan(self._results, direction)
        size = human_size(sum((d.left or d.right).size for d in plan))
        where = {LEFT_TO_RIGHT: "into the right folder", BOTH_WAYS: "both ways"}.get(direction, "into the left folder")
        return self.ask("Copy the missing files", f"Copy {len(plan)} file(s), {size}, {where}?\n\n"
                                                  "Nothing is overwritten, and the copy can be undone.")

    def apply_task(self):
        results, options = self._results, self.current_options()
        direction = self.direction_combo.currentData() or LEFT_TO_RIGHT
        return lambda progress, log, cancel: copy_missing(results, options, direction, progress, cancel, log)

    def on_applied(self, result) -> None:
        self.log("info", f"{result['done']} file(s) copied ({human_size(result['bytes'])}); "
                         f"{result['failed']} could not be.")
        self.scan()

    def can_undo(self) -> bool:
        return load_journal(TOOL) is not None

    def undo(self) -> None:
        journal = load_journal(TOOL)
        if journal is None:
            return
        if not self.ask("Undo last copy", f"Remove the {journal.count} file(s) copied on "
                                          f"{journal.when.replace('T', ' at ')}?\nThe originals stay where they are."):
            return
        count = undo_journal(journal, self.log)
        forget_journal(TOOL)
        self.log("info", f"{count} copied file(s) removed.")

    def screenshot_sample(self, sandbox: Path) -> None:
        left, right = sandbox / "Photos", sandbox / "Backup of Photos"
        for folder in (left, right):
            (folder / "2026").mkdir(parents=True, exist_ok=True)
        for name in ("2026/beach.jpg", "2026/dinner.jpg", "family.jpg"):
            (left / name).write_bytes(b"same" * 1000)
            (right / name).write_bytes(b"same" * 1000)
        (left / "2026/new trip.jpg").write_bytes(b"x" * 9000)
        (left / "family.jpg").write_bytes(b"edited" * 900)
        (right / "old scan.png").write_bytes(b"y" * 3000)
        self.left_input.setText(str(left))
        self.right_input.setText(str(right))
        select(self.show_combo, "all")
        select(self.direction_combo, BOTH_WAYS)
        self.on_scanned(self.run_now(self.scan_task()))
