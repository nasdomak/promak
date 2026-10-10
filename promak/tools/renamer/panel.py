"""The sequential folder renamer screen.

Left: which folder, in what order, how the new names look.  Middle: every
folder with its old and new name, updated as the options change, so the
result is seen before anything is touched.  Right: the activity log.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from promak.core.config import get_config
from promak.core.paths import open_in_file_manager
from promak.tools.renamer.engine import (
    ORDER_MANUAL,
    ORDER_NAME,
    ORDERS,
    CODE_EXAMPLES,
    CODE_PIECES,
    STYLE_CUSTOM,
    STYLE_NUMBER_NAME,
    STYLES,
    Rename,
    RenameError,
    RenameOptions,
    apply_renames,
    check_pattern,
    last_journal,
    list_folders,
    plan_renames,
    sort_folders,
    undo_renames,
)
from promak.ui.columns import activity_column, fit_setup_column, queue_buttons, side_by_side

log = logging.getLogger(__name__)

COL_OLD, COL_NEW, COL_NOTE = range(3)


class RenamerPanel(QWidget):
    """Number the folders inside a folder, with a preview and an undo."""

    TOOL_ID = "renamer"

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.config = get_config()
        self._folders: List[Path] = []
        self._plan: List[Rename] = []
        self.setAcceptDrops(True)
        self._build_ui()
        self._load_settings()
        self._refresh_undo()

    # ================================================================ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(6)
        title = QLabel("Number folders in sequence")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Gives the folders inside a folder names in sequence - 01, 02, 03 - keeping their "
            "old name or replacing it. You see every new name before anything is renamed, and "
            "the last renaming can be undone."
        )
        subtitle.setObjectName("PageSubtitle")
        subtitle.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addSpacing(8)

        activity, self.log_view = activity_column()
        outer.addWidget(
            side_by_side([self._build_setup(), self._build_preview(), activity],
                         f"{self.TOOL_ID}.column_widths"),
            1,
        )
        outer.addLayout(self._build_footer())

    def _build_setup(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        # --- 1. folder ---------------------------------------------------
        box = QGroupBox("1 - The folder that holds the folders")
        box_layout = QVBoxLayout(box)
        hint = QLabel("Drag a folder here, or pick it with the button.")
        hint.setObjectName("DropArea")
        hint.setAlignment(Qt.AlignCenter)
        hint.setMinimumHeight(60)
        hint.setWordWrap(True)
        box_layout.addWidget(hint)
        row = QHBoxLayout()
        self.folder_input = QLineEdit()
        self.folder_input.setPlaceholderText("For example  D:\\Photos\\2026")
        self.folder_input.editingFinished.connect(self.reload)
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        row.addWidget(self.folder_input, 1)
        row.addWidget(browse)
        box_layout.addLayout(row)
        self.count_label = QLabel("No folder chosen.")
        self.count_label.setObjectName("HintLabel")
        self.count_label.setWordWrap(True)
        box_layout.addWidget(self.count_label)
        layout.addWidget(box)

        # --- 2. order ----------------------------------------------------
        box = QGroupBox("2 - In what order")
        grid = QGridLayout(box)
        self.order_combo = QComboBox()
        for label, value in ORDERS:
            self.order_combo.addItem(label, value)
        self.order_combo.setToolTip(
            '"As I arrange them": select a row in the list and move it with the arrows.'
        )
        self.order_combo.currentIndexChanged.connect(self._on_order_changed)
        self.descending_check = QCheckBox("Reverse the order")
        self.descending_check.toggled.connect(self._on_order_changed)
        self.hidden_check = QCheckBox("Include hidden folders")
        self.hidden_check.toggled.connect(self.reload)
        grid.addWidget(QLabel("Order"), 0, 0)
        grid.addWidget(self.order_combo, 0, 1)
        grid.addWidget(self.descending_check, 1, 0, 1, 2)
        grid.addWidget(self.hidden_check, 2, 0, 1, 2)
        grid.setColumnStretch(1, 1)
        layout.addWidget(box)

        # --- 3. names ----------------------------------------------------
        box = QGroupBox("3 - How the new names look")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.style_combo = QComboBox()
        for label, value in STYLES:
            self.style_combo.addItem(label, value)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("optional, for example  Project")
        self.separator_input = QLineEdit()
        self.separator_input.setMaxLength(8)
        self.start_spin = QSpinBox()
        self.start_spin.setRange(-99999, 99999)
        self.step_spin = QSpinBox()
        self.step_spin.setRange(-1000, 1000)
        self.digits_spin = QSpinBox()
        self.digits_spin.setRange(0, 8)
        self.digits_spin.setSpecialValueText("automatic")
        self.digits_spin.setToolTip("01 has two digits, 001 three. Automatic uses just enough for the last number.")
        self.drop_check = QCheckBox("Replace a number already at the start of the name")
        self.drop_check.setToolTip('"07 - Holiday" becomes "01 - Holiday", not "01 - 07 - Holiday".')

        # --- my own code ---------------------------------------------------
        self.pattern_input = QLineEdit()
        self.pattern_input.setPlaceholderText("for example  PRJ-{year}-{n:3} {name}")
        self.pattern_input.setToolTip("\n".join(f"{piece}   {meaning}" for piece, meaning in CODE_PIECES))
        self.piece_combo = QComboBox()
        self.piece_combo.addItem("Insert a piece...", "")
        for piece, meaning in CODE_PIECES:
            self.piece_combo.addItem(f"{piece}   {meaning}", piece.split(" ")[0])
        self.piece_combo.activated.connect(self._insert_piece)
        self.saved_combo = QComboBox()
        self.saved_combo.setToolTip("Your saved codes, and a few examples to start from.")
        self.saved_combo.activated.connect(self._use_saved_code)
        save_code = QPushButton("Save")
        save_code.setToolTip("Keep this code in the list, to use it again another day.")
        save_code.clicked.connect(self._save_code)
        forget_code = QPushButton("Delete")
        forget_code.setToolTip("Take the chosen code out of your list.")
        forget_code.clicked.connect(self._forget_code)
        saved_row = QHBoxLayout()
        saved_row.addWidget(self.saved_combo, 1)
        saved_row.addWidget(save_code)
        saved_row.addWidget(forget_code)
        self.pieces_help = QLabel(
            "Write the name as you want it and put pieces in braces where the variable parts go: "
            "{n} the number, {name} the old name, {date} the folder's date, {letter}, {roman}, "
            "{parent}... Hover the code box for the full list."
        )
        self.pieces_help.setObjectName("HintLabel")
        self.pieces_help.setWordWrap(True)

        self._style_rows = {}
        rows = (
            ("Style", self.style_combo, "all"), ("Code", self.pattern_input, "custom"),
            ("", self.piece_combo, "custom"), ("My codes", saved_row, "custom"),
            ("", self.pieces_help, "custom"),
            ("Text", self.text_input, "plain"), ("Separator", self.separator_input, "plain"),
            ("First number", self.start_spin, "all"),
            ("Step", self.step_spin, "all"), ("Digits", self.digits_spin, "all"),
        )
        for index, (caption, widget, kind) in enumerate(rows):
            label = QLabel(caption)
            grid.addWidget(label, index, 0)
            if isinstance(widget, QHBoxLayout):
                holder = QWidget()
                holder.setLayout(widget)
                widget.setContentsMargins(0, 0, 0, 0)
                widget = holder
            grid.addWidget(widget, index, 1)
            self._style_rows.setdefault(kind, []).extend([label, widget])
        grid.addWidget(self.drop_check, len(rows), 0, 1, 2)
        layout.addWidget(box)
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)
        self.pattern_input.textChanged.connect(self.refresh_preview)

        for signal in (self.style_combo.currentIndexChanged, self.text_input.textChanged,
                       self.separator_input.textChanged, self.start_spin.valueChanged,
                       self.step_spin.valueChanged, self.digits_spin.valueChanged,
                       self.drop_check.toggled):
            signal.connect(self.refresh_preview)

        layout.addStretch(1)
        scroll.setWidget(container)
        fit_setup_column(scroll, container)
        return scroll

    def _build_preview(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(8)
        label = QLabel("Preview")
        label.setObjectName("SectionLabel")
        layout.addWidget(label)
        layout.addLayout(queue_buttons((
            ("Move up", lambda: self._move(-1)),
            ("Move down", lambda: self._move(1)),
            ("Read again", self.reload),
            ("Leave out selected", self._leave_out),
            ("Open folder", self._open_folder),
        )))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Now", "Will become", "Note"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_OLD, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_NEW, QHeaderView.Stretch)
        header.setSectionResizeMode(COL_NOTE, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_NOTE, 150)
        layout.addWidget(self.table, 1)
        return container

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("HintLabel")
        footer.addWidget(self.summary_label, 1)
        self.undo_button = QPushButton("Undo last renaming")
        self.undo_button.clicked.connect(self._undo)
        self.start_button = QPushButton("Rename the folders")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.setMinimumWidth(170)
        self.start_button.clicked.connect(self._apply)
        footer.addWidget(self.undo_button)
        footer.addWidget(self.start_button)
        return footer

    # ========================================================= settings
    def _load_settings(self) -> None:
        c = self.config
        self._select(self.order_combo, c.get("renamer.order", ORDER_NAME))
        self._select(self.style_combo, c.get("renamer.style", STYLE_NUMBER_NAME))
        self.descending_check.setChecked(bool(c.get("renamer.descending", False)))
        self.text_input.setText(c.get("renamer.text", "") or "")
        self.separator_input.setText(c.get("renamer.separator", " - "))
        self.start_spin.setValue(int(c.get("renamer.start", 1)))
        self.step_spin.setValue(int(c.get("renamer.step", 1)) or 1)
        self.digits_spin.setValue(int(c.get("renamer.digits", 2)))
        self.drop_check.setChecked(bool(c.get("renamer.drop_old_number", True)))
        self.pattern_input.setText(c.get("renamer.pattern", "{n} - {name}") or "{n} - {name}")
        self._fill_saved_codes()
        self._on_style_changed()
        self.folder_input.setText(c.get("renamer.folder", "") or "")
        if self.folder_input.text():
            self.reload()

    def save_settings(self) -> None:
        o = self.current_options()
        self.config.update({
            "renamer.order": o.order, "renamer.style": o.style, "renamer.descending": o.descending,
            "renamer.text": o.text, "renamer.separator": o.separator, "renamer.start": o.start,
            "renamer.step": o.step, "renamer.digits": o.digits,
            "renamer.drop_old_number": o.drop_old_number, "renamer.pattern": o.pattern,
            "renamer.folder": self.folder_input.text().strip(),
        })

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def current_options(self) -> RenameOptions:
        return RenameOptions(
            style=self.style_combo.currentData() or STYLE_NUMBER_NAME,
            start=self.start_spin.value(),
            step=self.step_spin.value(),
            digits=self.digits_spin.value(),
            separator=self.separator_input.text(),
            text=self.text_input.text(),
            order=self.order_combo.currentData() or ORDER_NAME,
            descending=self.descending_check.isChecked(),
            drop_old_number=self.drop_check.isChecked(),
            include_hidden=self.hidden_check.isChecked(),
            pattern=self.pattern_input.text(),
        )

    # ====================================================== my own code
    def _on_style_changed(self, *_args) -> None:
        custom = (self.style_combo.currentData() or "") == STYLE_CUSTOM
        for widget in self._style_rows.get("custom", []):
            widget.setVisible(custom)
        for widget in self._style_rows.get("plain", []):
            widget.setVisible(not custom)

    def _insert_piece(self, index: int) -> None:
        piece = self.piece_combo.itemData(index)
        self.piece_combo.setCurrentIndex(0)
        if piece:
            self.pattern_input.insert(piece)
            self.pattern_input.setFocus()

    def saved_codes(self) -> List[str]:
        codes = self.config.get("renamer.saved_patterns") or []
        return [c for c in codes if isinstance(c, str) and c.strip()]

    def _fill_saved_codes(self, select: str = "") -> None:
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("Choose a code...", "")
        for code in self.saved_codes():
            self.saved_combo.addItem(code, code)
        for code in CODE_EXAMPLES:
            if code not in self.saved_codes():
                self.saved_combo.addItem(f"{code}   (example)", code)
        index = self.saved_combo.findData(select) if select else 0
        self.saved_combo.setCurrentIndex(max(0, index))
        self.saved_combo.blockSignals(False)

    def _use_saved_code(self, index: int) -> None:
        code = self.saved_combo.itemData(index)
        if code:
            self.pattern_input.setText(code)

    def _save_code(self) -> None:
        code = self.pattern_input.text().strip()
        problem = check_pattern(code)
        if problem:
            QMessageBox.information(self, "Save the code", problem)
            return
        codes = [c for c in self.saved_codes() if c != code]
        self.config.set("renamer.saved_patterns", [code, *codes][:30])
        self._fill_saved_codes(select=code)
        self._log("info", f"Code saved: {code}")

    def _forget_code(self) -> None:
        code = self.saved_combo.currentData() or self.pattern_input.text().strip()
        codes = self.saved_codes()
        if code not in codes:
            return
        self.config.set("renamer.saved_patterns", [c for c in codes if c != code])
        self._fill_saved_codes()
        self._log("info", f"Code deleted: {code}")

    # ======================================================== the list
    def set_folder(self, folder: Path) -> None:
        self.folder_input.setText(str(folder))
        self.reload()

    def reload(self, *_args) -> None:
        text = self.folder_input.text().strip()
        self._folders = []
        if text:
            options = self.current_options()
            try:
                self._folders = list_folders(Path(text), options.order, options.descending,
                                             options.include_hidden)
            except RenameError as exc:
                self._log("error", str(exc))
        self.count_label.setText(
            f"{len(self._folders)} folder(s) found." if text else "No folder chosen."
        )
        self.refresh_preview()

    def _on_order_changed(self, *_args) -> None:
        options = self.current_options()
        if options.order != ORDER_MANUAL:
            try:
                self._folders = sort_folders(self._folders, options.order, options.descending)
            except OSError as exc:
                self._log("error", f"The folders cannot be read: {exc}")
        self.refresh_preview()

    def refresh_preview(self, *_args) -> None:
        options = self.current_options()
        problem = options.validate()
        self._plan = [] if problem else plan_renames(self._folders, options)
        self.table.setRowCount(0)
        for item in self._plan:
            row = self.table.rowCount()
            self.table.insertRow(row)
            old = QTableWidgetItem(item.source.name)
            old.setToolTip(str(item.source))
            self.table.setItem(row, COL_OLD, old)
            self.table.setItem(row, COL_NEW, QTableWidgetItem(item.new_name))
            note = item.problem or ("" if item.changes else "already right")
            note_item = QTableWidgetItem(note)
            note_item.setToolTip(note)
            self.table.setItem(row, COL_NOTE, note_item)
        changing = [i for i in self._plan if i.ok and i.changes]
        blocked = [i for i in self._plan if not i.ok]
        if problem:
            self.summary_label.setText(problem)
        elif not self._plan:
            self.summary_label.setText("")
        else:
            text = f"{len(changing)} folder(s) will be renamed."
            if blocked:
                text += f"  {len(blocked)} cannot be: see the Note column."
            self.summary_label.setText(text)
        self.start_button.setEnabled(bool(changing) and not blocked and not problem)
        self.start_button.setText(f"Rename {len(changing)} folder(s)" if changing else "Rename the folders")

    def _selected_rows(self) -> List[int]:
        model = self.table.selectionModel()
        return sorted({index.row() for index in model.selectedRows()}) if model else []

    def _move(self, delta: int) -> None:
        rows = self._selected_rows()
        if len(rows) != 1:
            QMessageBox.information(self, "Move a folder", "Select one row, then move it.")
            return
        row, target = rows[0], rows[0] + delta
        if not 0 <= target < len(self._folders):
            return
        self._folders[row], self._folders[target] = self._folders[target], self._folders[row]
        self.order_combo.blockSignals(True)
        self._select(self.order_combo, ORDER_MANUAL)
        self.order_combo.blockSignals(False)
        self.refresh_preview()
        self.table.selectRow(target)

    def _leave_out(self) -> None:
        rows = set(self._selected_rows())
        if rows:
            self._folders = [f for i, f in enumerate(self._folders) if i not in rows]
            self.refresh_preview()

    def _open_folder(self) -> None:
        text = self.folder_input.text().strip()
        if text:
            open_in_file_manager(Path(text))

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Folder that holds the folders",
                                                  self.folder_input.text().strip() or str(Path.home()))
        if folder:
            self.set_folder(Path(folder))

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_dir():
                self.set_folder(path)
                break
        event.acceptProposedAction()

    # ========================================================= actions
    def _apply(self) -> None:
        changing = [i for i in self._plan if i.ok and i.changes]
        if not changing:
            return
        answer = QMessageBox.question(
            self, "Rename the folders",
            f"Rename {len(changing)} folder(s)?\nYou can undo it afterwards with \"Undo last renaming\".",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        self.save_settings()
        try:
            journal = apply_renames(self._plan)
        except RenameError as exc:
            self._log("error", str(exc))
            QMessageBox.warning(self, "Nothing was renamed", str(exc))
            self.reload()
            return
        for old, new in journal.moves:
            self._log("info", f"{Path(old).name}  ->  {Path(new).name}")
        self._log("info", f"Renamed {len(journal.moves)} folder(s).")
        self._folders = [Path(new) for _old, new in journal.moves] + [
            i.source for i in self._plan if not (i.ok and i.changes)
        ]
        self.reload()
        self._refresh_undo()

    def _undo(self) -> None:
        journal = last_journal()
        if journal is None:
            return
        answer = QMessageBox.question(
            self, "Undo last renaming",
            f"Put back the old names of {len(journal.moves)} folder(s) in\n{journal.parent}?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            count = undo_renames(journal)
            self._log("info", f"Old names put back on {count} folder(s).")
        except (RenameError, OSError) as exc:
            self._log("error", str(exc))
            QMessageBox.warning(self, "Undo", str(exc))
        self.reload()
        self._refresh_undo()

    def _refresh_undo(self) -> None:
        journal = last_journal()
        self.undo_button.setEnabled(journal is not None)
        self.undo_button.setToolTip(
            f"{len(journal.moves)} folder(s) renamed on {journal.when.replace('T', ' at ')}\nin {journal.parent}"
            if journal else "Nothing to undo."
        )

    def _log(self, level: str, message: str) -> None:
        prefix = {"error": "[!]", "warning": "[*]"}.get(level, "[.]")
        self.log_view.appendPlainText(f"{prefix} {message}")

    # ------------------------------------------------------------ closing
    def shutdown(self) -> None:
        self.save_settings()

    def has_running_work(self) -> bool:
        return False

