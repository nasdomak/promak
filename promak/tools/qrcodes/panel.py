"""The QR code and barcode screen.

Left: what goes in the codes, how they look, where they are saved.
Middle: the codes themselves, drawn as they will be saved; a single code
is redrawn while you type.  Nothing is written before "Save".
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QSize, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from promak.tools.qrcodes.engine import (
    ERRORS,
    FORMATS,
    KINDS,
    QR,
    SOURCE_CSV,
    SOURCE_LIST,
    SOURCE_ONE,
    SOURCE_WIFI,
    SOURCES,
    Code,
    CodeOptions,
    collect_codes,
    preview,
    save_codes,
)
from promak.ui.plan_panel import ColourField, PlanPanel, combo, folder_field, select

SECURITY = [("WPA / WPA2 / WPA3 (usual)", "WPA"), ("WEP (old)", "WEP"), ("No password", "nopass")]


class QrCodesPanel(PlanPanel):
    """QR codes and barcodes, one or a whole list, as PNG or SVG."""

    TOOL_ID = "qrcodes"
    PAGE_TITLE = "QR codes and barcodes"
    PAGE_SUBTITLE = (
        "Makes QR codes for links, texts and Wi-Fi networks, and barcodes for products, books and "
        "stock - one, or one for every line of a list or row of a CSV file - as PNG pictures or "
        "SVG drawings that stay sharp at any size."
    )
    PREVIEW_TITLE = "The codes"
    SCAN_LABEL = "Show the codes"
    APPLY_LABEL = "Save the codes"
    COMPONENTS = ("segno", "barcode")

    def __init__(self, parent=None) -> None:
        self._codes: List[Code] = []
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(350)
        self._timer.timeout.connect(self._live_preview)
        for signal in (self.text_input.textChanged, self.wifi_name.textChanged, self.wifi_password.textChanged,
                       self.kind_combo.currentIndexChanged, self.error_combo.currentIndexChanged,
                       self.dark_field.textChanged, self.light_field.textChanged, self.border_spin.valueChanged,
                       self.transparent_check.toggled, self.text_check.toggled, self.security_combo.currentIndexChanged):
            signal.connect(lambda *_: self._timer.start())
        self._live_preview()

    # ============================================================== setup
    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - What goes in the code")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.kind_combo = combo(KINDS)
        self.source_combo = combo(SOURCES)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.kind_combo.currentIndexChanged.connect(self._on_source_changed)
        self.text_input = QPlainTextEdit()
        self.text_input.setPlaceholderText("https://www.example.org")
        self.text_input.setMinimumHeight(70)
        self.text_input.setMaximumHeight(140)
        csv_holder, self.csv_input = _file_field("The CSV file with the codes")
        self.csv_holder = csv_holder
        self.column_spin = QSpinBox()
        self.column_spin.setRange(1, 200)
        self.column_spin.setPrefix("column ")
        self.name_spin = QSpinBox()
        self.name_spin.setRange(0, 200)
        self.name_spin.setSpecialValueText("from the content")
        self.name_spin.setPrefix("column ")
        self.wifi_name = QLineEdit()
        self.wifi_name.setPlaceholderText("the network's name, as phones show it")
        self.wifi_password = QLineEdit()
        self.security_combo = combo(SECURITY)
        self._rows = {}
        rows = (("Code", self.kind_combo, "all"), ("Make", self.source_combo, "all"),
                ("Content", self.text_input, "text"), ("CSV file", csv_holder, "csv"),
                ("Content in", self.column_spin, "csv"), ("File names", self.name_spin, "csv"),
                ("Network", self.wifi_name, "wifi"), ("Password", self.wifi_password, "wifi"),
                ("Security", self.security_combo, "wifi"))
        for index, (caption, widget, kind) in enumerate(rows):
            label = QLabel(caption)
            grid.addWidget(label, index, 0)
            grid.addWidget(widget, index, 1)
            self._rows.setdefault(kind, []).extend([label, widget])
        self.source_hint = QLabel()
        self.source_hint.setObjectName("HintLabel")
        self.source_hint.setWordWrap(True)
        grid.addWidget(self.source_hint, len(rows), 0, 1, 2)
        layout.addWidget(box)

        box = QGroupBox("2 - How it looks")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.size_spin = QSpinBox()
        self.size_spin.setRange(64, 8000)
        self.size_spin.setSuffix(" px wide")
        self.error_combo = combo(ERRORS)
        self.dark_field = ColourField("#000000")
        self.light_field = ColourField("#FFFFFF")
        self.transparent_check = QCheckBox("Transparent background (PNG and SVG)")
        self.border_spin = QSpinBox()
        self.border_spin.setRange(0, 20)
        self.border_spin.setToolTip("The empty margin around the code. Scanners need some: 4 for QR codes.")
        self.text_check = QCheckBox("Write the digits under the bars")
        self.format_combo = combo(FORMATS)
        self.error_caption = QLabel("Error correction")
        grid.addWidget(QLabel("Size"), 0, 0)
        grid.addWidget(self.size_spin, 0, 1)
        grid.addWidget(self.error_caption, 1, 0)
        grid.addWidget(self.error_combo, 1, 1)
        grid.addWidget(QLabel("Code colour"), 2, 0)
        grid.addWidget(self.dark_field, 2, 1)
        grid.addWidget(QLabel("Background"), 3, 0)
        grid.addWidget(self.light_field, 3, 1)
        grid.addWidget(self.transparent_check, 4, 0, 1, 2)
        grid.addWidget(QLabel("Margin"), 5, 0)
        grid.addWidget(self.border_spin, 5, 1)
        grid.addWidget(self.text_check, 6, 0, 1, 2)
        grid.addWidget(QLabel("Save as"), 7, 0)
        grid.addWidget(self.format_combo, 7, 1)
        hint = QLabel("Keep the code dark on a light background: many scanners cannot read it the other way round.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        grid.addWidget(hint, 8, 0, 1, 2)
        layout.addWidget(box)

        box = QGroupBox("3 - Where to save them")
        grid = QGridLayout(box)
        holder, self.folder_input = folder_field("Folder for the codes", "Folder for the codes")
        self.overwrite_check = QCheckBox("Replace files with the same name")
        grid.addWidget(holder, 0, 0)
        grid.addWidget(self.overwrite_check, 1, 0)
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        self.codes_view = QListWidget()
        self.codes_view.setViewMode(QListView.IconMode)
        self.codes_view.setIconSize(QSize(180, 180))
        self.codes_view.setGridSize(QSize(210, 230))
        self.codes_view.setResizeMode(QListView.Adjust)
        self.codes_view.setMovement(QListView.Static)
        self.codes_view.setWordWrap(True)
        self.codes_view.setObjectName("PlainList")
        return self.codes_view

    # =========================================================== settings
    def current_options(self) -> CodeOptions:
        folder = self.folder_input.text().strip()
        csv_path = self.csv_input.text().strip()
        return CodeOptions(
            kind=self.kind_combo.currentData() or QR, source=self.source_combo.currentData() or SOURCE_ONE,
            text=self.text_input.toPlainText(), csv_path=Path(csv_path) if csv_path else None,
            csv_column=self.column_spin.value() - 1, name_column=self.name_spin.value() - 1,
            wifi_name=self.wifi_name.text(), wifi_password=self.wifi_password.text(),
            wifi_security=self.security_combo.currentData() or "WPA", size=self.size_spin.value(),
            error=self.error_combo.currentData() or "m", dark=self.dark_field.text(),
            light="transparent" if self.transparent_check.isChecked() else self.light_field.text(),
            border=self.border_spin.value(), show_text=self.text_check.isChecked(),
            output_format=self.format_combo.currentData() or "png",
            folder=Path(folder) if folder else None, overwrite=self.overwrite_check.isChecked(),
        )

    def load_settings(self) -> None:
        from promak.core.paths import default_output_dir

        c = self.config
        select(self.kind_combo, c.get("qrcodes.kind", QR))
        select(self.source_combo, c.get("qrcodes.source", SOURCE_ONE))
        self.text_input.setPlainText(c.get("qrcodes.text", "https://www.example.org") or "")
        self.size_spin.setValue(int(c.get("qrcodes.size", 600)))
        select(self.error_combo, c.get("qrcodes.error", "m"))
        self.dark_field.setText(c.get("qrcodes.dark", "#000000"))
        self.light_field.setText(c.get("qrcodes.light", "#FFFFFF"))
        self.transparent_check.setChecked(bool(c.get("qrcodes.transparent", False)))
        self.border_spin.setValue(int(c.get("qrcodes.border", 4)))
        self.text_check.setChecked(bool(c.get("qrcodes.show_text", True)))
        select(self.format_combo, c.get("qrcodes.format", "png"))
        self.folder_input.setText(c.get("qrcodes.folder", "") or str(default_output_dir() / "Codes"))
        self._on_source_changed()

    def save_settings(self) -> None:
        o = self.current_options()
        self.config.update({
            "qrcodes.kind": o.kind, "qrcodes.source": o.source, "qrcodes.text": o.text, "qrcodes.size": o.size,
            "qrcodes.error": o.error, "qrcodes.dark": o.dark, "qrcodes.light": self.light_field.text(),
            "qrcodes.transparent": self.transparent_check.isChecked(), "qrcodes.border": o.border,
            "qrcodes.show_text": o.show_text, "qrcodes.format": o.output_format,
            "qrcodes.folder": str(o.folder or ""),
        })

    def _on_source_changed(self, *_args) -> None:
        source = self.source_combo.currentData() or SOURCE_ONE
        is_qr = (self.kind_combo.currentData() or QR) == QR
        visible = {"all": True, "text": source in (SOURCE_ONE, SOURCE_LIST), "csv": source == SOURCE_CSV,
                   "wifi": source == SOURCE_WIFI}
        for kind, widgets in self._rows.items():
            for widget in widgets:
                widget.setVisible(visible[kind])
        self.error_caption.setVisible(is_qr)
        self.error_combo.setVisible(is_qr)
        self.text_check.setVisible(not is_qr)
        self.source_hint.setText({
            SOURCE_ONE: "A link, a phone number, any text. The code is drawn while you type.",
            SOURCE_LIST: "One code per line; each file is named after its line.",
            SOURCE_CSV: "One code per row. File names can come from another column, for example a product name.",
            SOURCE_WIFI: "Guests point the phone camera at the code and join the network without typing the password.",
        }[source])
        self.text_input.setPlaceholderText("https://www.example.org" if source == SOURCE_ONE
                                           else "first code\nsecond code\nthird code")
        if hasattr(self, "_timer"):
            self._timer.start()

    def on_dropped(self, paths) -> None:
        for path in paths:
            if path.suffix.lower() in (".csv", ".tsv", ".txt"):
                select(self.source_combo, SOURCE_CSV)
                self.csv_input.setText(str(path))
                return

    # ============================================================ preview
    def _live_preview(self) -> None:
        options = self.current_options()
        if options.source in (SOURCE_ONE, SOURCE_WIFI) and not options.validate():
            self.on_scanned(self._build(options, lambda *_: None, None))

    def validate_scan(self) -> Optional[str]:
        return self.current_options().validate()

    def scan_task(self):
        options = self.current_options()
        return lambda progress, log, cancel: self._build(options, progress, cancel)

    @staticmethod
    def _build(options: CodeOptions, progress, cancel):
        codes = collect_codes(options)
        pictures = []
        for index, code in enumerate(codes[:300], start=1):
            if cancel is not None and cancel.is_set():
                break
            data = b""
            if not code.problem:
                try:
                    data = preview(code, options, 180)
                except Exception as exc:  # shown under the code
                    code.problem = str(exc)
            pictures.append(data)
            progress(index / max(1, min(300, len(codes))), code.name)
        return codes, pictures

    def on_scanned(self, result) -> None:
        codes, pictures = result
        self._codes = codes
        self.codes_view.clear()
        for code, data in zip(codes, pictures):
            item = QListWidgetItem(code.name if not code.problem else f"{code.name}\n{code.problem}")
            item.setToolTip(code.content if not code.problem else code.problem)
            if data:
                pixmap = QPixmap()
                pixmap.loadFromData(data, "PNG")
                item.setIcon(QIcon(pixmap))
            self.codes_view.addItem(item)
        good = sum(1 for c in codes if not c.problem)
        more = f" (showing the first {len(pictures)})" if len(pictures) < len(codes) else ""
        self.summary_label.setText(f"{good} code(s) ready" + (f", {len(codes) - good} with a problem" if good < len(codes)
                                                              else "") + more)
        self.apply_button.setText(f"Save {good} code(s)" if good else self.APPLY_LABEL)
        self.refresh_buttons()

    # ============================================================== saving
    def can_apply(self) -> bool:
        return any(not c.problem for c in getattr(self, "_codes", []))

    def confirm_apply(self) -> bool:
        if not self.current_options().folder:
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, self.PAGE_TITLE, "Choose the folder where the codes are saved.")
            return False
        return True

    def apply_task(self):
        options, codes = self.current_options(), self._codes
        return lambda progress, log, cancel: save_codes(codes, options, progress, cancel)

    def on_applied(self, result) -> None:
        folder = self.current_options().folder
        self.log("info", f"{result['done']} code(s) saved in {folder}" +
                 (f"; {result['failed']} could not be made." if result["failed"] else "."))
        for code in self._codes:
            if code.problem:
                self.log("warning", f"{code.name}: {code.problem}")

    def screenshot_sample(self, sandbox: Path) -> None:
        select(self.source_combo, SOURCE_LIST)
        self.text_input.setPlainText("https://www.example.org\nWelcome to the shop\nTable 12\nMenu of the day")
        self.folder_input.setText(str(sandbox / "Codes"))
        self.on_scanned(self.run_now(self.scan_task()))


def _file_field(placeholder: str):
    """A line for a file path, with a Browse button."""
    from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QPushButton

    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    line = QLineEdit()
    line.setPlaceholderText(placeholder)
    browse = QPushButton("Browse...")

    def pick() -> None:
        path, _ = QFileDialog.getOpenFileName(holder, placeholder, line.text().strip() or str(Path.home()),
                                              "CSV files (*.csv *.tsv *.txt);;All files (*)")
        if path:
            line.setText(path)

    browse.clicked.connect(pick)
    row.addWidget(line, 1)
    row.addWidget(browse)
    return holder, line
