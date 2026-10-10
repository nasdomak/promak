"""The batch picture screen: resize, convert, watermark.

Queues, folders, drag and drop, progress and errors all come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the options.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSlider,
    QSpinBox,
)

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.picturebatch.engine import (
    FORMATS,
    KEEP_FORMAT,
    POSITIONS,
    RESIZE_MODES,
    RESIZE_NONE,
    RESIZE_PERCENT,
    SIZE_PRESETS,
    BatchOptions,
    PictureBatch,
)
from promak.ui.file_panel import FileQueuePanel


class PictureBatchPanel(FileQueuePanel):
    """Many pictures in, resized / converted / signed copies out."""

    TOOL_ID = "picturebatch"
    PAGE_TITLE = "Resize and convert pictures"
    PAGE_SUBTITLE = (
        "Makes every picture the size you need, saves it in the format you need and, if you "
        "like, signs it with your name - all the pictures in one go. Your originals are "
        "never changed."
    )
    FILES_BOX_TITLE = "1 - Pictures"
    FILES_HINT = "Drag your pictures here.\nJPG, PNG, WEBP, TIFF, BMP and GIF."
    DESTINATION_BOX_TITLE = "2 - Where to save the new copies"
    OPTIONS_BOX_TITLE = "3 - What to do"
    EXTRA_COLUMNS = ("Before", "After")
    START_LABEL = "Do it"
    RUNNING_LABEL = "Working..."

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        row = 0

        # --- size --------------------------------------------------------
        self.resize_combo = QComboBox()
        for label, value in RESIZE_MODES:
            self.resize_combo.addItem(label, value)
        self.resize_combo.currentIndexChanged.connect(self._on_resize_changed)
        grid.addWidget(QLabel("Size"), row, 0)
        grid.addWidget(self.resize_combo, row, 1)
        row += 1
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 20000)
        self.preset_combo = QComboBox()
        self.preset_combo.addItem("Ready-made sizes...", 0)
        for label, value in SIZE_PRESETS:
            self.preset_combo.addItem(label, value)
        self.preset_combo.currentIndexChanged.connect(self._on_preset)
        size_row = QHBoxLayout()
        size_row.addWidget(self.size_spin)
        size_row.addWidget(self.preset_combo, 1)
        grid.addLayout(size_row, row, 1)
        row += 1
        self.enlarge_check = QCheckBox("Also enlarge pictures smaller than this")
        self.enlarge_check.setToolTip("Off: a small picture stays as it is instead of going blurry.")
        grid.addWidget(self.enlarge_check, row, 0, 1, 2)
        row += 1

        # --- format ------------------------------------------------------
        self.format_combo = QComboBox()
        for label, value in FORMATS:
            self.format_combo.addItem(label, value)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        grid.addWidget(QLabel("Format"), row, 0)
        grid.addWidget(self.format_combo, row, 1)
        row += 1
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(40, 98)
        self.quality_label = QLabel()
        self.quality_slider.valueChanged.connect(lambda v: self.quality_label.setText(f"Quality {v}"))
        quality_row = QHBoxLayout()
        quality_row.addWidget(self.quality_slider, 1)
        quality_row.addWidget(self.quality_label)
        grid.addWidget(QLabel("JPG / WEBP"), row, 0)
        grid.addLayout(quality_row, row, 1)
        row += 1

        # --- watermark ---------------------------------------------------
        self.watermark_input = QLineEdit()
        self.watermark_input.setPlaceholderText("optional, for example  © Your name 2026")
        grid.addWidget(QLabel("Watermark"), row, 0)
        grid.addWidget(self.watermark_input, row, 1)
        row += 1
        self.position_combo = QComboBox()
        for label, value in POSITIONS:
            self.position_combo.addItem(label, value)
        grid.addWidget(QLabel("Where"), row, 0)
        grid.addWidget(self.position_combo, row, 1)
        row += 1
        self.opacity_spin = QSpinBox()
        self.opacity_spin.setRange(5, 100)
        self.opacity_spin.setSuffix(" % visible")
        self.text_size_spin = QSpinBox()
        self.text_size_spin.setRange(1, 30)
        self.text_size_spin.setSuffix(" % tall")
        self.text_size_spin.setToolTip("Height of the text, as a share of the picture's shorter side.")
        look_row = QHBoxLayout()
        look_row.addWidget(self.opacity_spin)
        look_row.addWidget(self.text_size_spin)
        grid.addWidget(QLabel("Look"), row, 0)
        grid.addLayout(look_row, row, 1)
        row += 1

        # --- names -------------------------------------------------------
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("optional, for example  -web")
        self.suffix_input.setToolTip("Added to the end of every new file name: photo-web.jpg")
        grid.addWidget(QLabel("Add to names"), row, 0)
        grid.addWidget(self.suffix_input, row, 1)
        row += 1
        self.overwrite_check = QCheckBox("Redo files that already exist")
        grid.addWidget(self.overwrite_check, row, 0, 1, 2)

    # ----------------------------------------------------------- settings
    def current_options(self) -> BatchOptions:
        return BatchOptions(
            resize_mode=self.resize_combo.currentData() or RESIZE_NONE,
            size=self.size_spin.value(),
            allow_enlarge=self.enlarge_check.isChecked(),
            output_format=self.format_combo.currentData() or KEEP_FORMAT,
            quality=self.quality_slider.value(),
            watermark_text=self.watermark_input.text(),
            watermark_position=self.position_combo.currentData() or "bottom-right",
            watermark_opacity=self.opacity_spin.value(),
            watermark_size=self.text_size_spin.value(),
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
        self._select(self.resize_combo, c.get("picturebatch.resize_mode", "longest"))
        self.size_spin.setValue(int(c.get("picturebatch.size", 1600)))
        self.enlarge_check.setChecked(bool(c.get("picturebatch.allow_enlarge", False)))
        self._select(self.format_combo, c.get("picturebatch.format", KEEP_FORMAT))
        self.quality_slider.setValue(int(c.get("picturebatch.quality", 88)))
        self.quality_label.setText(f"Quality {self.quality_slider.value()}")
        self.watermark_input.setText(c.get("picturebatch.watermark", "") or "")
        self._select(self.position_combo, c.get("picturebatch.position", "bottom-right"))
        self.opacity_spin.setValue(int(c.get("picturebatch.opacity", 50)))
        self.text_size_spin.setValue(int(c.get("picturebatch.text_size", 4)))
        self.suffix_input.setText(c.get("picturebatch.suffix", "") or "")
        self.overwrite_check.setChecked(bool(c.get("picturebatch.overwrite", False)))
        self._on_resize_changed()
        self._on_format_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({
            "picturebatch.resize_mode": o.resize_mode, "picturebatch.size": o.size,
            "picturebatch.allow_enlarge": o.allow_enlarge, "picturebatch.format": o.output_format,
            "picturebatch.quality": o.quality, "picturebatch.watermark": o.watermark_text,
            "picturebatch.position": o.watermark_position, "picturebatch.opacity": o.watermark_opacity,
            "picturebatch.text_size": o.watermark_size, "picturebatch.suffix": o.suffix,
            "picturebatch.overwrite": o.overwrite,
        })

    def _on_resize_changed(self, *_args) -> None:
        mode = self.resize_combo.currentData() or RESIZE_NONE
        for widget in (self.size_spin, self.preset_combo, self.enlarge_check):
            widget.setEnabled(mode != RESIZE_NONE)
        self.preset_combo.setEnabled(mode not in (RESIZE_NONE, RESIZE_PERCENT))
        self.size_spin.setSuffix(" %" if mode == RESIZE_PERCENT else " px")

    def _on_preset(self, *_args) -> None:
        value = self.preset_combo.currentData()
        if value:
            self.size_spin.setValue(int(value))

    def _on_format_changed(self, *_args) -> None:
        fmt = self.format_combo.currentData() or KEEP_FORMAT
        self.quality_slider.setEnabled(fmt != "PNG")

    # ------------------------------------------------------------ running
    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return PictureBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (job.info.get("before", ""), job.info.get("after", ""))
