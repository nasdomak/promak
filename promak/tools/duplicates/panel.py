"""The duplicate finder screen.

Left: where to look, what counts as a duplicate, which copy to keep and
what to do with the others.  Middle: the groups found, one file per line
with a tick on the ones that will go, and below them the pictures of the
selected group side by side.  Nothing happens to any file before the
button is pressed and the question answered.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from promak.core.fileops import forget_journal, load_journal, undo_journal
from promak.core.imaging import RASTER_EXTENSIONS, human_size
from promak.tools.duplicates.engine import (
    ACTIONS,
    EXACT,
    KEEP_LARGEST,
    KEEP_RULES,
    MODES,
    SIMILAR,
    TO_BIN,
    TO_FOLDER,
    TOOL,
    DuplicateOptions,
    Group,
    check_groups,
    find_duplicates,
    mark,
    marked,
    remove_duplicates,
    summary_text,
)
from promak.ui.plan_panel import FolderList, PlanPanel, combo, folder_field, select

ROLE = Qt.UserRole


class DuplicatesPanel(PlanPanel):
    """Find duplicate files and similar pictures; bin or move the extra copies."""

    TOOL_ID = "duplicates"
    PAGE_TITLE = "Find duplicates"
    PAGE_SUBTITLE = (
        "Finds files that are exact copies of each other, or pictures that look the same, and "
        "keeps the best of each group. The others go to the Recycle Bin or to a folder of your "
        "choice - nothing is ever deleted outright, and you see every group first."
    )
    PREVIEW_TITLE = "Groups found  (ticked = will go)"
    SCAN_LABEL = "Look for duplicates"
    APPLY_LABEL = "Remove the ticked files"
    UNDO_LABEL = "Undo last move"
    COMPONENTS = ("send2trash", "imagehash")

    def __init__(self, parent=None) -> None:
        self._groups: List[Group] = []
        self._filling = False
        super().__init__(parent)

    # ============================================================ setup
    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - Where to look")
        inner = QVBoxLayout(box)
        self.folders = FolderList("Drag folders here, or use Add folder. Several folders are compared together.")
        inner.addWidget(self.folders)
        self.recursive_check = QCheckBox("Also look inside their sub-folders")
        inner.addWidget(self.recursive_check)
        layout.addWidget(box)

        box = QGroupBox("2 - What counts as a duplicate")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.mode_combo = combo(MODES)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.similarity_slider = QSlider(Qt.Horizontal)
        self.similarity_slider.setRange(70, 100)
        self.similarity_label = QLabel()
        self.similarity_slider.valueChanged.connect(self._on_similarity_changed)
        slider_row = QHBoxLayout()
        slider_row.addWidget(self.similarity_slider, 1)
        slider_row.addWidget(self.similarity_label)
        self.min_spin = QSpinBox()
        self.min_spin.setRange(0, 1024 * 1024)
        self.min_spin.setSuffix(" KB")
        self.min_spin.setToolTip("Smaller files are left out (tiny icons, empty files).")
        grid.addWidget(QLabel("Search"), 0, 0)
        grid.addWidget(self.mode_combo, 0, 1)
        self.similarity_caption = QLabel("Similarity")
        grid.addWidget(self.similarity_caption, 1, 0)
        self.similarity_holder = QWidget()
        self.similarity_holder.setLayout(slider_row)
        slider_row.setContentsMargins(0, 0, 0, 0)
        grid.addWidget(self.similarity_holder, 1, 1)
        self.similarity_hint = QLabel("100% = only pictures that look identical; lower finds more, "
                                      "also pictures that are merely alike - check them before removing.")
        self.similarity_hint.setObjectName("HintLabel")
        self.similarity_hint.setWordWrap(True)
        grid.addWidget(self.similarity_hint, 2, 0, 1, 2)
        grid.addWidget(QLabel("Ignore below"), 3, 0)
        grid.addWidget(self.min_spin, 3, 1)
        layout.addWidget(box)

        box = QGroupBox("3 - What to keep, and where the others go")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.keep_combo = combo(KEEP_RULES)
        self.keep_combo.currentIndexChanged.connect(self._remark)
        self.action_combo = combo(ACTIONS)
        self.action_combo.currentIndexChanged.connect(self._on_action_changed)
        holder, self.move_input = folder_field("Folder for the removed copies", "Folder for the removed copies")
        self.move_holder = holder
        grid.addWidget(QLabel("Keep"), 0, 0)
        grid.addWidget(self.keep_combo, 0, 1)
        grid.addWidget(QLabel("The others"), 1, 0)
        grid.addWidget(self.action_combo, 1, 1)
        grid.addWidget(holder, 2, 1)
        hint = QLabel("Untick a file in the list to keep it too, tick one to remove it. Files in the "
                      "Recycle Bin can be put back from there; a move can be undone here.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        grid.addWidget(hint, 3, 0, 1, 2)
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["File", "Size", "Changed", "Folder"])
        self.tree.setAlternatingRowColors(True)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for column, width in ((1, 80), (2, 120), (3, 160)):
            header.setSectionResizeMode(column, QHeaderView.Interactive)
            self.tree.setColumnWidth(column, width)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(lambda *_: self._show_group())
        splitter.addWidget(self.tree)

        strip = QScrollArea()
        strip.setWidgetResizable(True)
        strip.setFrameShape(QFrame.NoFrame)
        strip.setMinimumHeight(200)
        self.side_by_side = QWidget()
        self.side_row = QHBoxLayout(self.side_by_side)
        self.side_row.setContentsMargins(0, 0, 0, 0)
        self.side_row.setSpacing(10)
        strip.setWidget(self.side_by_side)
        splitter.addWidget(strip)
        splitter.setSizes([520, 240])
        return splitter

    def preview_buttons(self):
        return (
            ("Keep the suggested ones", self._remark),
            ("Untick the group", self._untick_group),
            ("Open folder", self._open_selected),
        )

    # ========================================================= settings
    def current_options(self) -> DuplicateOptions:
        move_to = self.move_input.text().strip()
        return DuplicateOptions(
            folders=self.folders.folders(),
            recursive=self.recursive_check.isChecked(),
            mode=self.mode_combo.currentData() or EXACT,
            similarity=self.similarity_slider.value(),
            min_kb=self.min_spin.value(),
            keep=self.keep_combo.currentData() or KEEP_LARGEST,
            action=self.action_combo.currentData() or TO_BIN,
            move_to=Path(move_to) if move_to else None,
        )

    def load_settings(self) -> None:
        c = self.config
        self.folders.set_folders(c.get("duplicates.folders") or [])
        self.recursive_check.setChecked(bool(c.get("duplicates.recursive", True)))
        select(self.mode_combo, c.get("duplicates.mode", EXACT))
        self.similarity_slider.setValue(int(c.get("duplicates.similarity", 92)))
        self.min_spin.setValue(int(c.get("duplicates.min_kb", 1)))
        select(self.keep_combo, c.get("duplicates.keep", KEEP_LARGEST))
        select(self.action_combo, c.get("duplicates.action", TO_BIN))
        self.move_input.setText(c.get("duplicates.move_to", "") or "")
        self._on_mode_changed()
        self._on_action_changed()
        self._on_similarity_changed(self.similarity_slider.value())

    def save_settings(self) -> None:
        o = self.current_options()
        self.config.update({
            "duplicates.folders": [str(f) for f in o.folders], "duplicates.recursive": o.recursive,
            "duplicates.mode": o.mode, "duplicates.similarity": o.similarity, "duplicates.min_kb": o.min_kb,
            "duplicates.keep": o.keep, "duplicates.action": o.action,
            "duplicates.move_to": str(o.move_to or ""),
        })

    def _on_mode_changed(self, *_args) -> None:
        similar = self.mode_combo.currentData() == SIMILAR
        for widget in (self.similarity_caption, self.similarity_holder, self.similarity_hint):
            widget.setVisible(similar)

    def _on_similarity_changed(self, value: int) -> None:
        self.similarity_label.setText(f"{value}%")

    def _on_action_changed(self, *_args) -> None:
        self.move_holder.setVisible(self.action_combo.currentData() == TO_FOLDER)
        self._refresh_summary()

    def on_dropped(self, paths) -> None:
        for path in paths:
            self.folders.add(path if path.is_dir() else path.parent)

    # =========================================================== looking
    def validate_scan(self) -> Optional[str]:
        return self.current_options().validate()

    def scan_task(self):
        options = self.current_options()
        return lambda progress, log, cancel: find_duplicates(options, progress, cancel)

    def on_scanned(self, groups) -> None:
        self._groups = list(groups or [])
        self._fill_tree()
        self.log("info", summary_text(self._groups))

    def _fill_tree(self) -> None:
        self._filling = True
        self.tree.clear()
        for number, group in enumerate(self._groups, start=1):
            parent = QTreeWidgetItem(self.tree)
            parent.setData(0, ROLE, ("group", number - 1))
            parent.setFirstColumnSpanned(True)
            for entry_index, entry in enumerate(group.entries):
                item = QTreeWidgetItem(parent, [entry.path.name, human_size(entry.size), entry.date_text,
                                                str(entry.path.parent)])
                item.setToolTip(0, str(entry.path))
                item.setToolTip(3, str(entry.path.parent))
                item.setData(0, ROLE, ("entry", number - 1, entry_index))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(0, Qt.Checked if entry.remove else Qt.Unchecked)
            parent.setExpanded(True)
            self._title_group(parent, group, number)
        self._filling = False
        if self._groups:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self._show_group()
        self._refresh_summary()

    @staticmethod
    def _title_group(item: QTreeWidgetItem, group: Group, number: int) -> None:
        kind = "similar pictures" if group.kind == SIMILAR else "identical files"
        item.setText(0, f"Group {number} - {len(group.entries)} {kind} - "
                        f"{human_size(group.freed_bytes)} freed")

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._filling or column != 0:
            return
        data = item.data(0, ROLE)
        if not data or data[0] != "entry":
            return
        group = self._groups[data[1]]
        group.entries[data[2]].remove = item.checkState(0) == Qt.Checked
        self._title_group(item.parent(), group, data[1] + 1)
        self._refresh_summary()
        self._show_group()

    def _current_group(self) -> Optional[int]:
        item = self.tree.currentItem()
        if item is None:
            return None
        data = item.data(0, ROLE)
        return data[1] if data else None

    def _remark(self, *_args) -> None:
        rule = self.keep_combo.currentData() or KEEP_LARGEST
        for group in self._groups:
            mark(group, rule)
        if self._groups:
            current = self._current_group()
            self._fill_tree()
            if current is not None and current < self.tree.topLevelItemCount():
                self.tree.setCurrentItem(self.tree.topLevelItem(current))

    def _untick_group(self) -> None:
        index = self._current_group()
        if index is None:
            return
        for entry in self._groups[index].entries:
            entry.remove = False
        self._fill_tree()
        self.tree.setCurrentItem(self.tree.topLevelItem(index))

    def _open_selected(self) -> None:
        from promak.core.paths import open_in_file_manager

        item = self.tree.currentItem()
        data = item.data(0, ROLE) if item else None
        if data and data[0] == "entry":
            open_in_file_manager(self._groups[data[1]].entries[data[2]].path)

    def _show_group(self) -> None:
        while self.side_row.count():
            widget = self.side_row.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        index = self._current_group()
        if index is None or index >= len(self._groups):
            hint = QLabel("Select a group to see its files side by side.")
            hint.setObjectName("HintLabel")
            self.side_row.addWidget(hint)
            self.side_row.addStretch(1)
            return
        for entry in self._groups[index].entries[:6]:
            self.side_row.addWidget(_FileCard(entry.path, entry.remove, f"{human_size(entry.size)}"
                                              f"  {entry.date_text}"))
        self.side_row.addStretch(1)

    def _refresh_summary(self) -> None:
        going = marked(self._groups)
        noun = "Recycle Bin" if (self.action_combo.currentData() or TO_BIN) == TO_BIN else "folder"
        self.apply_button.setText(f"Move {len(going)} file(s) to the {noun}" if going else self.APPLY_LABEL)
        self.summary_label.setText(summary_text(self._groups) if self._groups else "")
        self.refresh_buttons()

    # ============================================================ acting
    def can_apply(self) -> bool:
        return bool(marked(getattr(self, "_groups", [])))

    def confirm_apply(self) -> bool:
        options = self.current_options()
        problem = check_groups(self._groups) or options.validate_action()
        if problem:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, self.PAGE_TITLE, problem)
            return False
        going = marked(self._groups)
        size = human_size(sum(e.size for e in going))
        where = ("to the Recycle Bin (you can put them back from there)" if options.action == TO_BIN
                 else f"to\n{options.move_to}\n(you can undo it with \"Undo last move\")")
        return self.ask("Remove the duplicates",
                        f"Move {len(going)} file(s), {size}, {where}?\n\nOne file of every group stays where it is.",
                        default_yes=False)

    def apply_task(self):
        options, groups = self.current_options(), self._groups
        return lambda progress, log, cancel: remove_duplicates(groups, options, progress, cancel, log)

    def on_applied(self, result) -> None:
        self.log("info", f"{result['done']} file(s) removed, {human_size(result['bytes'])} freed; "
                         f"{result['failed']} could not be.")
        # what is left is looked at again next time; the list starts empty
        self._groups = []
        self._fill_tree()

    def can_undo(self) -> bool:
        return load_journal(TOOL) is not None

    def undo(self) -> None:
        journal = load_journal(TOOL)
        if journal is None:
            return
        if not self.ask("Undo last move", f"Put {journal.count} moved file(s) back where they were?"):
            return
        count = undo_journal(journal, self.log)
        forget_journal(TOOL)
        self.log("info", f"{count} file(s) put back.")

    # ------------------------------------------------------- screenshots
    def screenshot_sample(self, sandbox: Path) -> None:
        """Used by tools/screenshots.py: two folders with copies in them."""
        from PIL import Image, ImageDraw

        phone, laptop = sandbox / "Phone backup", sandbox / "Laptop pictures"
        for folder in (phone, laptop):
            folder.mkdir(parents=True, exist_ok=True)
        for index, (name, colour) in enumerate((("beach.jpg", (40, 130, 210)), ("dinner.jpg", (220, 120, 40)))):
            image = Image.new("RGB", (900, 600), colour)
            ImageDraw.Draw(image).ellipse((200 + index * 80, 100, 600, 500), fill=(250, 240, 200))
            image.save(phone / name, quality=92)
            image.save(laptop / f"Copy of {name}", quality=92)
            image.resize((450, 300)).save(laptop / f"{Path(name).stem}-small.jpg", quality=80)
        self.folders.set_folders([phone, laptop])
        select(self.mode_combo, SIMILAR)
        self.on_scanned(self.run_now(self.scan_task()))
        self.tree.setCurrentItem(self.tree.topLevelItem(0))


class _FileCard(QFrame):
    """One file of a group, drawn as a picture when it is one."""

    def __init__(self, path: Path, goes: bool, caption: str, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("PreviewBox")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)
        heading = QLabel("GOES" if goes else "KEEP")
        heading.setObjectName("PreviewTitle")
        heading.setAlignment(Qt.AlignCenter)
        layout.addWidget(heading)
        image = QLabel()
        image.setObjectName("PreviewImage")
        image.setAlignment(Qt.AlignCenter)
        image.setFixedSize(170, 128)
        pixmap = QPixmap(str(path)) if path.suffix.lower() in RASTER_EXTENSIONS else QPixmap()
        if pixmap.isNull():
            image.setText(path.suffix.upper().lstrip(".") or "file")
        else:
            image.setPixmap(pixmap.scaled(166, 124, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        layout.addWidget(image)
        name = QLabel(path.name)
        name.setObjectName("PreviewCaption")
        name.setAlignment(Qt.AlignCenter)
        name.setToolTip(str(path))
        name.setMaximumWidth(170)
        layout.addWidget(name)
        details = QLabel(caption)
        details.setObjectName("PreviewCaption")
        details.setAlignment(Qt.AlignCenter)
        layout.addWidget(details)
