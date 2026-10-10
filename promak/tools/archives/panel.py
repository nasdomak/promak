"""The archives screen: make a ZIP or 7z, or open ZIP, 7z and TAR files.

Left: what to do, the files, the options.  Middle: what is (or will be)
inside, listed before anything is written.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from promak.core.imaging import human_size
from promak.tools.archives.engine import (
    ARCHIVE_EXTENSIONS,
    FORMATS,
    LEVELS,
    ZIP,
    ArchiveError,
    Entry,
    MakeOptions,
    archive_kind,
    describe,
    extract_archive,
    list_archive,
    make_archive,
    plan_items,
)
from promak.ui.plan_panel import PlanPanel, combo, folder_field, make_table, select

MAKE = "make"
OPEN = "open"
MODES = [("Make an archive (ZIP or 7z)", MAKE), ("Open archives (ZIP, 7z, TAR)", OPEN)]


class ArchivesPanel(PlanPanel):
    """Make ZIP and 7z archives; list and extract ZIP, 7z and TAR."""

    TOOL_ID = "archives"
    PAGE_TITLE = "Archives"
    PAGE_SUBTITLE = (
        "Packs files and folders into a ZIP (with an AES password if you like) or a 7z, and opens "
        "ZIP, 7z and TAR archives - listing what is inside first. Archives that try to write "
        "outside their folder are refused."
    )
    PREVIEW_TITLE = "What is inside"
    SCAN_LABEL = "Show the contents"
    APPLY_LABEL = "Make the archive"
    COMPONENTS = ("pyzipper", "py7zr")

    def __init__(self, parent=None) -> None:
        self._entries: List[Tuple[str, Entry]] = []
        super().__init__(parent)

    # ============================================================== setup
    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - What to do")
        inner = QVBoxLayout(box)
        self.mode_combo = combo(MODES)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        inner.addWidget(self.mode_combo)
        layout.addWidget(box)

        self.items_box = QGroupBox("2 - Files and folders")
        inner = QVBoxLayout(self.items_box)
        self.items = QListWidget()
        self.items.setObjectName("PlainList")
        self.items.setMinimumHeight(110)
        self.items.setMaximumHeight(170)
        inner.addWidget(self.items)
        row = QHBoxLayout()
        self.add_files_button = QPushButton("Add files...")
        self.add_files_button.clicked.connect(self._add_files)
        self.add_folder_button = QPushButton("Add a folder...")
        self.add_folder_button.clicked.connect(self._add_folder)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        row.addWidget(self.add_files_button, 1)
        row.addWidget(self.add_folder_button, 1)
        row.addWidget(remove, 1)
        inner.addLayout(row)
        self.items_hint = QLabel()
        self.items_hint.setObjectName("HintLabel")
        self.items_hint.setWordWrap(True)
        inner.addWidget(self.items_hint)
        layout.addWidget(self.items_box)

        box = QGroupBox("3 - Options")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.format_combo = combo(FORMATS)
        self.level_combo = combo(LEVELS)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("for example  Holiday photos")
        holder, self.folder_input = folder_field("Folder for the archive", "Folder")
        self.own_folder_check = QCheckBox("Each archive in a folder of its own")
        self.password_input = QLineEdit()
        self.password_input.setEchoMode(QLineEdit.Password)
        show = QCheckBox("Show")
        show.toggled.connect(lambda on: self.password_input.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.overwrite_check = QCheckBox("Replace files that are already there")
        self.password_hint = QLabel()
        self.password_hint.setObjectName("HintLabel")
        self.password_hint.setWordWrap(True)
        self._rows = {}
        rows = (("Format", self.format_combo, MAKE), ("Compression", self.level_combo, MAKE),
                ("Name", self.name_input, MAKE), ("Save in", holder, "all"), ("", self.own_folder_check, OPEN),
                ("Password", self.password_input, "all"), ("", show, "all"), ("", self.password_hint, "all"),
                ("", self.overwrite_check, "all"))
        for index, (caption, widget, kind) in enumerate(rows):
            label = QLabel(caption)
            grid.addWidget(label, index, 0)
            grid.addWidget(widget, index, 1)
            self._rows.setdefault(kind, []).extend([label, widget])
        self.folder_caption = grid.itemAtPosition(3, 0).widget()
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        self.table = make_table(("Name", "Size", "Date", "Note"), stretch=(0,))
        self.table.setColumnWidth(2, 130)
        return self.table

    # ============================================================== items
    def mode(self) -> str:
        return self.mode_combo.currentData() or MAKE

    def item_paths(self) -> List[Path]:
        return [Path(self.items.item(i).text()) for i in range(self.items.count())]

    def add_items(self, paths) -> None:
        known = {self.items.item(i).text() for i in range(self.items.count())}
        for path in paths:
            path = Path(path)
            if self.mode() == OPEN and (not path.is_file() or archive_kind(path) is None):
                continue
            if str(path) not in known:
                self.items.addItem(str(path))
                known.add(str(path))
        self._entries = []
        self._fill()

    def _add_files(self) -> None:
        if self.mode() == OPEN:
            pattern = "Archives (" + " ".join(f"*{e}" for e in ARCHIVE_EXTENSIONS) + ");;All files (*)"
        else:
            pattern = "All files (*)"
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files", str(Path.home()), pattern)
        self.add_items(files)

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder", str(Path.home()))
        if folder:
            self.add_items([folder])

    def _remove(self) -> None:
        for item in self.items.selectedItems():
            self.items.takeItem(self.items.row(item))
        self._entries = []
        self._fill()

    def on_dropped(self, paths) -> None:
        if self.mode() == MAKE and all(archive_kind(p) for p in paths if p.is_file()) and \
                not any(p.is_dir() for p in paths) and not self.items.count():
            select(self.mode_combo, OPEN)   # archives dropped on an empty screen: open them
        self.add_items(paths)

    def _on_mode_changed(self, *_args) -> None:
        mode = self.mode()
        for kind, widgets in self._rows.items():
            for widget in widgets:
                widget.setVisible(kind == "all" or kind == mode)
        self.add_folder_button.setVisible(mode == MAKE)
        self.items_box.setTitle("2 - Files and folders to pack" if mode == MAKE else "2 - Archives to open")
        self.items_hint.setText("Folders go in with their name and everything inside them."
                                if mode == MAKE else "Drag ZIP, 7z or TAR files here.")
        self.password_hint.setText(
            "Optional. ZIP uses AES-256 (opens in 7-Zip, WinRAR and most programs; Windows' own "
            "Explorer cannot open AES ZIP files). With 7z the file names are hidden too." if mode == MAKE
            else "Only for protected archives.")
        if self.folder_caption is not None:
            self.folder_caption.setText("Save in" if mode == MAKE else "Extract to")
        self.items.clear()
        self._entries = []
        self._fill()

    # ========================================================= settings
    def make_options(self) -> MakeOptions:
        folder = self.folder_input.text().strip()
        name = self.name_input.text().strip() or (self.item_paths()[0].stem if self.items.count() else "archive")
        fmt = self.format_combo.currentData() or ZIP
        return MakeOptions(items=self.item_paths(), target=Path(folder) / f"{name}.{fmt}" if folder else None,
                           fmt=fmt, level=int(self.level_combo.currentData() if self.level_combo.currentData()
                                              is not None else 6),
                           password=self.password_input.text(), overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        from promak.core.paths import default_output_dir

        c = self.config
        select(self.format_combo, c.get("archives.format", ZIP))
        select(self.level_combo, int(c.get("archives.level", 6)))
        self.folder_input.setText(c.get("archives.folder", "") or str(default_output_dir()))
        self.own_folder_check.setChecked(bool(c.get("archives.own_folder", True)))
        self._on_mode_changed()

    def save_settings(self) -> None:
        self.config.update({"archives.format": self.format_combo.currentData(),
                            "archives.level": self.level_combo.currentData(),
                            "archives.folder": self.folder_input.text().strip(),
                            "archives.own_folder": self.own_folder_check.isChecked()})

    # ============================================================ looking
    def validate_scan(self) -> Optional[str]:
        if not self.items.count():
            return "Add the files first."
        return None

    def scan_task(self):
        mode, paths, password = self.mode(), self.item_paths(), self.password_input.text()

        def task(progress, log, cancel):
            entries: List[Tuple[str, Entry]] = []
            if mode == MAKE:
                for file, arcname in plan_items(paths):
                    try:
                        size = file.stat().st_size
                    except OSError:
                        size = 0
                    entries.append(("", Entry(arcname, size)))
                return entries
            for index, path in enumerate(paths, start=1):
                try:
                    found = list_archive(path, password)
                    log("info", f"{path.name}: {describe(found)}")
                    entries.extend((path.name, entry) for entry in found)
                except ArchiveError as exc:
                    log("error", f"{path.name}: {exc}")
                    entries.append((path.name, Entry("(cannot be read)", 0, problem=str(exc))))
                progress(index / len(paths), path.name)
            return entries

        return task

    def on_scanned(self, entries) -> None:
        self._entries = list(entries or [])
        self._fill()

    def _fill(self) -> None:
        self.table.setRowCount(0)
        for archive, entry in self._entries[:5000]:
            if entry.folder:
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            name = QTableWidgetItem(f"{archive}  >  {entry.name}" if archive else entry.name)
            name.setToolTip(entry.name)
            self.table.setItem(row, 0, name)
            self.table.setItem(row, 1, QTableWidgetItem(human_size(entry.size)))
            self.table.setItem(row, 2, QTableWidgetItem(entry.when_text))
            note = entry.problem or ("protected" if entry.encrypted else "")
            self.table.setItem(row, 3, QTableWidgetItem(note))
        files = [e for _a, e in self._entries if not e.folder]
        if self.mode() == MAKE:
            self.apply_button.setText("Make the archive")
            text = f"{len(files)} file(s), {human_size(sum(e.size for e in files))} to pack." if files else ""
        else:
            self.apply_button.setText(f"Extract {self.items.count()} archive(s)" if self.items.count() else "Extract")
            text = f"{len(files)} file(s) inside." if files else ""
        self.summary_label.setText(text)
        self.refresh_buttons()

    # ============================================================= acting
    def can_apply(self) -> bool:
        return bool(getattr(self, "items", None) and self.items.count())

    def confirm_apply(self) -> bool:
        from PySide6.QtWidgets import QMessageBox

        if self.mode() == MAKE:
            problem = self.make_options().validate()
            if problem:
                QMessageBox.warning(self, self.PAGE_TITLE, problem)
                return False
            return True
        if not self.folder_input.text().strip():
            QMessageBox.warning(self, self.PAGE_TITLE, "Choose where the archives are extracted.")
            return False
        return True

    def apply_task(self):
        if self.mode() == MAKE:
            options = self.make_options()
            return lambda progress, log, cancel: ("make", *make_archive(options, progress, cancel))
        paths, password = self.item_paths(), self.password_input.text()
        destination, own = Path(self.folder_input.text().strip()), self.own_folder_check.isChecked()
        overwrite = self.overwrite_check.isChecked()

        def task(progress, log, cancel):
            results = []
            for index, path in enumerate(paths):
                share = (lambda s, t="", i=index: progress((i + s) / len(paths), t))
                try:
                    folder, count = extract_archive(path, destination, password, own, overwrite, share, cancel)
                    log("info", f"{path.name}: {count} file(s) into {folder}")
                    results.append((path, folder, count))
                except ArchiveError as exc:
                    log("error", f"{path.name}: {exc}")
            return ("open", results)

        return task

    def on_applied(self, result) -> None:
        if result[0] == "make":
            _kind, target, count = result
            self.log("info", f"{count} file(s) packed into {target} ({human_size(target.stat().st_size)}).")
        else:
            done = result[1]
            self.log("info", f"{len(done)} of {self.items.count()} archive(s) extracted.")

    def screenshot_sample(self, sandbox: Path) -> None:
        folder = sandbox / "Project files"
        (folder / "drawings").mkdir(parents=True, exist_ok=True)
        for name in ("offer.pdf", "budget.xlsx", "drawings/plan-1.png", "drawings/plan-2.png"):
            (folder / name).write_bytes(b"\0" * 40_000)
        self.folder_input.setText(str(sandbox / "Downloads" / "Promak"))
        self.name_input.setText("Project files")
        self.add_items([folder])
        self.on_scanned(self.run_now(self.scan_task()))
