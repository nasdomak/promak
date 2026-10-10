"""The "GIF and collage" screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; the order of the queue is the
order of the frames, or of the pictures in the grid.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QSpinBox

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.gifcollage.engine import (
    ACCEPTED_EXTENSIONS,
    COLLAGE,
    COLLAGE_FORMATS,
    FIT_WHOLE,
    FITS,
    GIF,
    JOBS,
    GifCollageBatch,
    GifOptions,
    grid_size,
)
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import ColourField, combo, select


class GifCollagePanel(FileQueuePanel):
    """Pictures in; one animated GIF or one collage out."""

    TOOL_ID = "gifcollage"
    PAGE_TITLE = "GIF and collage"
    PAGE_SUBTITLE = (
        "Turns a series of pictures into an animated GIF (or WEBP) that loops, or lays them out in a "
        "collage grid with the spacing and background you like. The order of the queue is the order "
        "of the pictures. Your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Pictures (in order)"
    FILES_HINT = "Drag your pictures here.\nUse Move up / Move down to put them in order."
    ITEM_WORD = "pictures"
    DESTINATION_BOX_TITLE = "2 - Where to save the result"
    OPTIONS_BOX_TITLE = "3 - What to make"
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    EXTRA_COLUMNS = ("Size",)
    EXTRA_COLUMN_WIDTH = 90
    START_LABEL = "Make it"
    REORDERABLE = True

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.job_combo = combo(JOBS)
        self.job_combo.currentIndexChanged.connect(self._on_job_changed)
        self.frame_spin = QSpinBox()
        self.frame_spin.setRange(20, 60000)
        self.frame_spin.setSingleStep(100)
        self.frame_spin.setSuffix(" ms per picture")
        self.loop_spin = QSpinBox()
        self.loop_spin.setRange(0, 100)
        self.loop_spin.setSpecialValueText("for ever")
        self.loop_spin.setSuffix(" time(s)")
        self.size_spin = QSpinBox()
        self.size_spin.setRange(32, 8000)
        self.size_spin.setSuffix(" px")
        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(0, 50)
        self.columns_spin.setSpecialValueText("worked out")
        self.columns_spin.valueChanged.connect(self._show_grid)
        self.spacing_spin = QSpinBox()
        self.spacing_spin.setRange(0, 400)
        self.spacing_spin.setSuffix(" px")
        self.fit_combo = combo(FITS)
        self.format_combo = combo(COLLAGE_FORMATS)
        self.background_field = ColourField("#FFFFFF")
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("optional - the first picture's name")
        self.overwrite_check = QCheckBox("Replace a file with the same name")
        self.grid_label = QLabel()
        self.grid_label.setObjectName("HintLabel")
        self.size_caption = QLabel("Size")
        self._kind_rows = {}
        rows = (("Make", self.job_combo, "all"), ("Each picture", self.frame_spin, "anim"),
                ("Play", self.loop_spin, "anim"), ("", self.size_caption, "skip"),
                ("Columns", self.columns_spin, "collage"), ("", self.grid_label, "collage"),
                ("Spacing", self.spacing_spin, "collage"), ("Pictures", self.fit_combo, "collage"),
                ("Save as", self.format_combo, "collage"), ("Background", self.background_field, "all"),
                ("File name", self.name_input, "all"))
        row = 0
        for caption, widget, kind in rows:
            if kind == "skip":
                grid.addWidget(self.size_caption, row, 0)
                grid.addWidget(self.size_spin, row, 1)
                row += 1
                continue
            label = QLabel(caption)
            grid.addWidget(label, row, 0)
            grid.addWidget(widget, row, 1)
            self._kind_rows.setdefault(kind, []).extend([label, widget])
            row += 1
        grid.addWidget(self.overwrite_check, row, 0, 1, 2)

    def _on_job_changed(self, *_args) -> None:
        collage = (self.job_combo.currentData() or GIF) == COLLAGE
        for kind, widgets in self._kind_rows.items():
            for widget in widgets:
                widget.setVisible(kind == "all" or (kind == "collage") == collage)
        self.size_caption.setText("Each cell" if collage else "Longest side")
        self._show_grid()

    def _show_grid(self, *_args) -> None:
        count = len(self._jobs) if hasattr(self, "_jobs") else 0
        columns, rows = grid_size(count, self.columns_spin.value())
        self.grid_label.setText(f"{count} picture(s): {columns} column(s) by {rows} row(s)" if count else "")

    def add_files(self, paths) -> None:
        super().add_files(paths)
        self._show_grid()

    def current_options(self) -> GifOptions:
        return GifOptions(job=self.job_combo.currentData() or GIF, frame_ms=self.frame_spin.value(),
                          loops=self.loop_spin.value(), size=self.size_spin.value(),
                          columns=self.columns_spin.value(), spacing=self.spacing_spin.value(),
                          background=self.background_field.text(), fit=self.fit_combo.currentData() or FIT_WHOLE,
                          collage_format=self.format_combo.currentData() or "JPEG", name=self.name_input.text(),
                          overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        select(self.job_combo, c.get("gifcollage.job", GIF))
        self.frame_spin.setValue(int(c.get("gifcollage.frame_ms", 600)))
        self.loop_spin.setValue(int(c.get("gifcollage.loops", 0)))
        self.size_spin.setValue(int(c.get("gifcollage.size", 800)))
        self.columns_spin.setValue(int(c.get("gifcollage.columns", 0)))
        self.spacing_spin.setValue(int(c.get("gifcollage.spacing", 12)))
        select(self.fit_combo, c.get("gifcollage.fit", FIT_WHOLE))
        select(self.format_combo, c.get("gifcollage.format", "JPEG"))
        self.background_field.setText(c.get("gifcollage.background", "#FFFFFF"))
        self.overwrite_check.setChecked(bool(c.get("gifcollage.overwrite", False)))
        self._on_job_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"gifcollage.job": o.job, "gifcollage.frame_ms": o.frame_ms, "gifcollage.loops": o.loops,
                            "gifcollage.size": o.size, "gifcollage.columns": o.columns,
                            "gifcollage.spacing": o.spacing, "gifcollage.fit": o.fit,
                            "gifcollage.format": o.collage_format, "gifcollage.background": o.background,
                            "gifcollage.overwrite": o.overwrite})

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return GifCollageBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        problem = self.current_options().validate()
        if problem:
            return problem
        if len([j for j in self._jobs if not j.stage.is_final]) < 2:
            return "Add at least two pictures."
        return None

    def extra_values(self, job: FileJob) -> Sequence[str]:
        if "size" not in job.info:
            from promak.core.imaging import photo_facts

            _taken, width, height = photo_facts(job.source)
            job.info["size"] = f"{width} x {height}" if width else "?"
        return (job.info.get("size", ""),)
