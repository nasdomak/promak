"""The "sort by date" screen.

Left: where the photos are, where the dated folders go, how they are
named.  Middle: every file, the date found and the folder it goes to.
Nothing moves before the button is pressed; the last run can be undone.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from promak.core.fileops import COPY, MOVE, forget_journal, load_journal, undo_journal
from promak.tools.sortdate.engine import (
    DEFAULT_PATTERN,
    PATTERN_EXAMPLES,
    PATTERN_PIECES,
    TOOL,
    Move,
    SortOptions,
    apply_sort,
    check_pattern,
    plan_sort,
    summary_text,
)
from promak.ui.plan_panel import FolderList, PlanPanel, combo, folder_field, make_table, select

ACTIONS = [("Move them (the photo folder is tidied)", MOVE), ("Copy them (the originals stay)", COPY)]


class SortDatePanel(PlanPanel):
    """Photos and videos into YYYY/MM - Month folders, with a preview and undo."""

    TOOL_ID = "sortdate"
    PAGE_TITLE = "Sort photos by date"
    PAGE_SUBTITLE = (
        "Puts photos and videos into one folder per month - 2026/07 - July - using the date the "
        "photo was taken, the recording date of a video, or the file's own date. You see where "
        "every file goes before anything moves, and the last run can be undone."
    )
    PREVIEW_TITLE = "Where every file goes"
    SCAN_LABEL = "Show the plan"
    APPLY_LABEL = "Sort the files"
    UNDO_LABEL = "Undo last sorting"

    def __init__(self, parent=None) -> None:
        self._plan: List[Move] = []
        super().__init__(parent)

    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - Where the photos and videos are")
        inner = QVBoxLayout(box)
        self.folders = FolderList("Drag the folders here (a phone backup, a camera card...).")
        inner.addWidget(self.folders)
        self.recursive_check = QCheckBox("Also look inside their sub-folders")
        self.all_check = QCheckBox("Every kind of file, not only photos and videos")
        inner.addWidget(self.recursive_check)
        inner.addWidget(self.all_check)
        layout.addWidget(box)

        box = QGroupBox("2 - Where the dated folders are made")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        holder, self.target_input = folder_field("For example  D:\\Photos by date", "Folder for the dated folders")
        self.action_combo = combo(ACTIONS)
        grid.addWidget(holder, 0, 0, 1, 2)
        grid.addWidget(QLabel("The files"), 1, 0)
        grid.addWidget(self.action_combo, 1, 1)
        hint = QLabel("It may be the same folder the photos are in: they are then sorted in place.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        grid.addWidget(hint, 2, 0, 1, 2)
        layout.addWidget(box)

        box = QGroupBox("3 - How the folders are named")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.pattern_input = QLineEdit()
        self.pattern_input.setToolTip("\n".join(f"{piece}   {meaning}" for piece, meaning in PATTERN_PIECES))
        self.examples_combo = QComboBox()
        self.examples_combo.addItem("Ready-made codes...", "")
        for example in PATTERN_EXAMPLES:
            self.examples_combo.addItem(example, example)
        self.examples_combo.activated.connect(self._use_example)
        self.file_date_check = QCheckBox("No date taken? Use the file's own date")
        self.file_date_check.setToolTip("When unticked, files without a camera or recording date go to 'No date'.")
        pieces = QLabel("Pieces: " + "  ".join(piece for piece, _m in PATTERN_PIECES) + "  - hover the box for more.")
        pieces.setObjectName("HintLabel")
        pieces.setWordWrap(True)
        self.example_label = QLabel()
        self.example_label.setObjectName("HintLabel")
        self.pattern_input.textChanged.connect(self._show_example)
        grid.addWidget(QLabel("Code"), 0, 0)
        grid.addWidget(self.pattern_input, 0, 1)
        grid.addWidget(self.examples_combo, 1, 1)
        grid.addWidget(pieces, 2, 0, 1, 2)
        grid.addWidget(self.example_label, 3, 0, 1, 2)
        grid.addWidget(self.file_date_check, 4, 0, 1, 2)
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        self.table = make_table(("File", "Date", "Found from", "Goes to", "Note"), stretch=(0, 3))
        self.table.setColumnWidth(1, 135)
        return self.table

    def preview_buttons(self):
        return (("Leave out selected", self._leave_out), ("Open target folder", self._open_target))

    # ------------------------------------------------------------ settings
    def current_options(self) -> SortOptions:
        target = self.target_input.text().strip()
        return SortOptions(
            folders=self.folders.folders(), recursive=self.recursive_check.isChecked(),
            target=Path(target) if target else None, action=self.action_combo.currentData() or MOVE,
            pattern=self.pattern_input.text().strip(), all_files=self.all_check.isChecked(),
            use_file_date=self.file_date_check.isChecked(),
        )

    def load_settings(self) -> None:
        c = self.config
        self.folders.set_folders(c.get("sortdate.folders") or [])
        self.recursive_check.setChecked(bool(c.get("sortdate.recursive", True)))
        self.all_check.setChecked(bool(c.get("sortdate.all_files", False)))
        self.target_input.setText(c.get("sortdate.target", "") or "")
        select(self.action_combo, c.get("sortdate.action", MOVE))
        self.pattern_input.setText(c.get("sortdate.pattern", DEFAULT_PATTERN) or DEFAULT_PATTERN)
        self.file_date_check.setChecked(bool(c.get("sortdate.use_file_date", True)))
        self._show_example()

    def save_settings(self) -> None:
        o = self.current_options()
        self.config.update({
            "sortdate.folders": [str(f) for f in o.folders], "sortdate.recursive": o.recursive,
            "sortdate.all_files": o.all_files, "sortdate.target": str(o.target or ""),
            "sortdate.action": o.action, "sortdate.pattern": o.pattern, "sortdate.use_file_date": o.use_file_date,
        })

    def _use_example(self, index: int) -> None:
        code = self.examples_combo.itemData(index)
        self.examples_combo.setCurrentIndex(0)
        if code:
            self.pattern_input.setText(code)

    def _show_example(self, *_args) -> None:
        from datetime import datetime

        from promak.tools.sortdate.engine import folder_for

        pattern = self.pattern_input.text().strip()
        problem = check_pattern(pattern)
        if problem:
            self.example_label.setText(problem)
            return
        example = folder_for(Path("IMG_2031.jpg"), datetime(2026, 7, 12, 10, 30), pattern)
        self.example_label.setText(f"A photo taken on 12 July 2026 goes to:  {example.as_posix()}/")

    def on_dropped(self, paths) -> None:
        for path in paths:
            self.folders.add(path if path.is_dir() else path.parent)

    # ------------------------------------------------------------ planning
    def validate_scan(self) -> Optional[str]:
        return self.current_options().validate()

    def scan_task(self):
        options = self.current_options()
        return lambda progress, log, cancel: plan_sort(options, progress, cancel)

    def on_scanned(self, plan) -> None:
        self._plan = list(plan or [])
        self._fill()
        self.log("info", summary_text(self._plan, self.current_options().action))

    def _fill(self) -> None:
        target = self.current_options().target
        self.table.setRowCount(0)
        for move in self._plan:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = QTableWidgetItem(move.source.name)
            name.setToolTip(str(move.source))
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(move.when.strftime("%Y-%m-%d %H:%M") if move.when else "-"))
            self.table.setItem(row, 2, QTableWidgetItem(move.found_by))
            try:
                shown = move.target.parent.relative_to(target).as_posix() + "/" if target else str(move.target.parent)
            except ValueError:
                shown = str(move.target.parent)
            goes = QTableWidgetItem(shown)
            goes.setToolTip(str(move.target))
            self.table.setItem(row, 3, goes)
            self.table.setItem(row, 4, QTableWidgetItem(move.note))
        self.summary_label.setText(summary_text(self._plan, self.current_options().action) if self._plan else "")
        going = [m for m in self._plan if m.ok]
        verb = "Copy" if self.current_options().action == COPY else "Move"
        self.apply_button.setText(f"{verb} {len(going)} file(s)" if going else self.APPLY_LABEL)
        self.refresh_buttons()

    def _leave_out(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()})
        if rows:
            self._plan = [m for i, m in enumerate(self._plan) if i not in rows]
            self._fill()

    def _open_target(self) -> None:
        from promak.core.paths import open_in_file_manager

        target = self.current_options().target
        if target and target.exists():
            open_in_file_manager(target)

    # -------------------------------------------------------------- acting
    def can_apply(self) -> bool:
        return any(m.ok for m in getattr(self, "_plan", []))

    def confirm_apply(self) -> bool:
        options = self.current_options()
        going = [m for m in self._plan if m.ok]
        verb = "Copy" if options.action == COPY else "Move"
        return self.ask("Sort the files", f"{verb} {len(going)} file(s) into dated folders in\n{options.target}?\n\n"
                                          "Nothing is overwritten, and you can undo it afterwards.")

    def apply_task(self):
        plan, options = self._plan, self.current_options()
        return lambda progress, log, cancel: apply_sort(plan, options, progress, cancel, log)

    def on_applied(self, result) -> None:
        self.log("info", f"{result['done']} file(s) sorted; {result['failed']} could not be.")
        self._plan = []
        self._fill()

    def can_undo(self) -> bool:
        return load_journal(TOOL) is not None

    def undo(self) -> None:
        journal = load_journal(TOOL)
        if journal is None:
            return
        if not self.ask("Undo last sorting", f"Put back the {journal.count} file(s) of the last sorting "
                                             f"({journal.when.replace('T', ' at ')})?"):
            return
        count = undo_journal(journal, self.log)
        forget_journal(TOOL)
        self.log("info", f"{count} file(s) put back.")

    # ---------------------------------------------------------- screenshots
    def screenshot_sample(self, sandbox: Path) -> None:
        from PIL import Image

        card = sandbox / "Camera card"
        card.mkdir(parents=True, exist_ok=True)
        for index, (name, taken) in enumerate((("IMG_2031.JPG", "2026:07:12 10:30:00"),
                                               ("IMG_2032.JPG", "2026:07:12 18:02:00"),
                                               ("IMG_2107.JPG", "2026:08:03 09:15:00"),
                                               ("IMG_2290.JPG", "2026:09:21 16:40:00"))):
            exif = Image.Exif()
            exif.get_ifd(0x8769)[36867] = taken
            Image.new("RGB", (64, 48), (50 * index, 120, 200)).save(card / name, exif=exif)
        Image.new("RGB", (64, 48)).save(card / "scan of a letter.png")
        self.folders.set_folders([card])
        self.target_input.setText(str(sandbox / "Photos by date"))
        self.on_scanned(self.run_now(self.scan_task()))
