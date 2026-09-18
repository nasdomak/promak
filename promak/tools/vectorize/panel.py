"""The vectoriser screen.

Everything about queues, folders, drag and drop, progress and errors is
inherited from :class:`promak.ui.file_panel.FileQueuePanel`.  What is left
here is only what makes this tool different: the options, and the
before/after preview that shows on screen that the result really is made
of shapes.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from promak.core.batch import BatchEngine
from promak.core.dependencies import missing_image_dependencies, refresh as refresh_dependencies
from promak.core.filejobs import FileJob
from promak.core.imaging import ImageToolError, human_size, read_facts
from promak.tools.vectorize.engine import VectorizeBatch, advice_for
from promak.tools.vectorize.models import (
    COLOUR_MODES,
    DETAIL_LEVELS,
    MAX_SIDE_CHOICES,
    SHAPE_MODES,
    VectorizeOptions,
)
from promak.ui.file_panel import FileQueuePanel
from promak.ui.preview import PreviewPair

log = logging.getLogger(__name__)

class VectorizePanel(FileQueuePanel):
    """Pictures in, real vector shapes out."""

    TOOL_ID = "vectorize"
    PAGE_TITLE = "Picture to vector (SVG)"
    PAGE_SUBTITLE = (
        "Redraws a logo, an icon or a drawing with shapes and curves, so it can be "
        "enlarged to any size - a business card or a lorry - without ever going blurry."
    )
    FILES_BOX_TITLE = "1 - Pictures to redraw"
    FILES_HINT = (
        "Drag your pictures here.\n"
        "Best results with logos, icons, line drawings and flat colours."
    )
    DESTINATION_BOX_TITLE = "2 - Where to save the SVG files"
    OPTIONS_BOX_TITLE = "3 - How to redraw them"
    EXTRA_COLUMNS = ("Before", "After", "Shapes")
    START_LABEL = "Redraw as vector"
    RUNNING_LABEL = "Redrawing..."

    # ==================================================================
    # options
    # ==================================================================
    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        # --- colour ------------------------------------------------------
        self.colour_combo = QComboBox()
        for label, value in COLOUR_MODES:
            self.colour_combo.addItem(label, value)
        self.colour_combo.setToolTip(
            "Colour keeps every shade as its own shape.\n"
            "Black and white gives one clean silhouette - ideal for stamps, "
            "engraving, cutting and embroidery."
        )
        grid.addWidget(QLabel("Colours"), 0, 0)
        grid.addWidget(self.colour_combo, 0, 1)

        # --- shape kind --------------------------------------------------
        self.shape_combo = QComboBox()
        for label, value in SHAPE_MODES:
            self.shape_combo.addItem(label, value)
        self.shape_combo.setToolTip(
            "Curves follow round edges smoothly.\n"
            "Straight lines give an angular, technical look and a lighter file."
        )
        grid.addWidget(QLabel("Edges"), 0, 2)
        grid.addWidget(self.shape_combo, 0, 3)

        # --- detail slider ----------------------------------------------
        self.detail_slider = QSlider(Qt.Horizontal)
        self.detail_slider.setRange(1, 5)
        self.detail_slider.setSingleStep(1)
        self.detail_slider.setPageStep(1)
        self.detail_slider.setTickPosition(QSlider.TicksBelow)
        self.detail_slider.setTickInterval(1)
        self.detail_slider.valueChanged.connect(self._on_detail_changed)
        grid.addWidget(QLabel("Detail"), 1, 0)
        grid.addWidget(self.detail_slider, 1, 1)

        self.detail_label = QLabel()
        self.detail_label.setObjectName("HintLabel")
        self.detail_label.setWordWrap(True)
        grid.addWidget(self.detail_label, 1, 2, 1, 2)

        # --- tracing size -----------------------------------------------
        self.size_combo = QComboBox()
        for label, value in MAX_SIDE_CHOICES:
            self.size_combo.addItem(label, value)
        self.size_combo.setToolTip(
            "The size the picture is read at before being redrawn.\n"
            "The result is made of curves, so it has no size of its own: reading a "
            "huge picture only makes a heavier file, not a better one."
        )
        grid.addWidget(QLabel("Read at"), 2, 0)
        grid.addWidget(self.size_combo, 2, 1)

        checks = QVBoxLayout()
        checks.setSpacing(4)
        self.background_check = QCheckBox("Put a white background behind see-through parts")
        self.background_check.setToolTip(
            "Leave this off to keep transparency. Turn it on when the picture has a "
            "see-through background and you want a solid white sheet instead."
        )
        self.overwrite_check = QCheckBox("Redo files that already exist")
        self.overwrite_check.setToolTip(
            "Off: a picture already converted in the destination folder is left alone.\n"
            "On: it is converted again and the old SVG is replaced."
        )
        checks.addWidget(self.background_check)
        checks.addWidget(self.overwrite_check)
        grid.addLayout(checks, 2, 2, 1, 2)

        for widget in (self.colour_combo, self.shape_combo, self.size_combo):
            widget.currentIndexChanged.connect(self._on_option_changed)
        for widget in (self.background_check, self.overwrite_check):
            widget.toggled.connect(self._on_option_changed)

        self.components_label = QLabel()
        self.components_label.setObjectName("HintLabel")
        self.components_label.setWordWrap(True)
        grid.addWidget(self.components_label, 3, 0, 1, 3)

        check_button = QPushButton("Check components")
        check_button.clicked.connect(self._check_components)
        grid.addWidget(check_button, 3, 3)

    def build_extra_area(self) -> Optional[QWidget]:
        box = QGroupBox("Before and after")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(8)

        self.previews = PreviewPair("Original picture", "Redrawn as shapes")
        layout.addWidget(self.previews)

        hint = QLabel(
            "Select a row in the queue to see its picture here. After a conversion the "
            "right-hand side is drawn from the SVG itself, so what you see on screen is "
            "the real vector file."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return box

    # ==================================================================
    # settings
    # ==================================================================
    def current_options(self) -> VectorizeOptions:
        return VectorizeOptions(
            colour_mode=self.colour_combo.currentData() or "colour",
            detail=int(self.detail_slider.value()),
            shape_mode=self.shape_combo.currentData() or "spline",
            max_side=int(self.size_combo.currentData() or 0),
            keep_background=self.background_check.isChecked(),
            overwrite=self.overwrite_check.isChecked(),
        )

    def load_settings(self) -> None:
        super().load_settings()
        config = self.config
        self._select_data(self.colour_combo, config.get("vectorize.colour_mode", "colour"))
        self._select_data(self.shape_combo, config.get("vectorize.shape_mode", "spline"))
        self._select_data(self.size_combo, int(config.get("vectorize.max_side", 1600) or 0))
        self.detail_slider.setValue(int(config.get("vectorize.detail", 3) or 3))
        self.background_check.setChecked(bool(config.get("vectorize.keep_background", False)))
        self.overwrite_check.setChecked(bool(config.get("vectorize.overwrite", False)))
        self._on_detail_changed(self.detail_slider.value())
        self._refresh_components(quiet=True)

    def save_settings(self) -> None:
        super().save_settings()
        options = self.current_options()
        self.config.update(
            {
                "vectorize.colour_mode": options.colour_mode,
                "vectorize.detail": options.clamped_detail,
                "vectorize.shape_mode": options.shape_mode,
                "vectorize.max_side": options.max_side,
                "vectorize.keep_background": options.keep_background,
                "vectorize.overwrite": options.overwrite,
            }
        )

    @staticmethod
    def _select_data(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _on_detail_changed(self, value: int) -> None:
        self.detail_label.setText(DETAIL_LEVELS.get(int(value), ""))
        self._on_option_changed()

    def _on_option_changed(self, *_args) -> None:
        # The options are only saved when a run starts, but the tooltip-like
        # summary is worth keeping honest at all times.
        self.detail_slider.setToolTip(self.current_options().describe())

    # ==================================================================
    # components
    # ==================================================================
    def _refresh_components(self, *, quiet: bool = False) -> None:
        missing = missing_image_dependencies(["pillow", "vtracer"])
        if not missing:
            self.components_label.setText("Components: Pillow OK  -  vectoriser OK")
            if not quiet:
                self.show_notice("")
            return
        names = ", ".join(d.label for d in missing)
        commands = "\n".join(d.install_command for d in missing)
        self.components_label.setText(f"Components missing: {names}")
        self.show_notice(
            f"This tool cannot run yet: {names} is not installed. "
            f"Install it with:  {commands}",
            "error",
        )

    def _check_components(self) -> None:
        refresh_dependencies()
        self._refresh_components()

    # ==================================================================
    # running
    # ==================================================================
    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return VectorizeBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        missing = missing_image_dependencies(["pillow", "vtracer"])
        if missing:
            return (
                "These components are missing: "
                + ", ".join(d.label for d in missing)
                + ".\n\nInstall them with:\n"
                + "\n".join(d.install_command for d in missing)
            )
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        before = human_size(job.source_bytes) if job.source_bytes else ""
        after = human_size(job.output_bytes) if job.output_bytes else ""
        return (before, after, job.info.get("shapes", ""))

    # ==================================================================
    # preview
    # ==================================================================
    def on_job_selected(self, job: Optional[FileJob]) -> None:
        if job is None:
            self.previews.clear()
            return
        self._show_before(job)
        self._show_after(job)

    def on_job_finished(self, job: FileJob) -> None:
        selected = self._selected_jobs()
        if not selected or selected[0].id == job.id:
            self._show_before(job)
            self._show_after(job)

    def _show_before(self, job: FileJob) -> None:
        caption = human_size(job.source_bytes)
        try:
            facts = read_facts(job.source)
            caption = f"{facts.width} x {facts.height} pixels  -  {human_size(facts.file_bytes)}"
            notes = advice_for(facts)
            self.show_notice(notes[0] if notes else "", "warning")
        except ImageToolError as exc:
            self.show_notice(str(exc), "error")
        self.previews.before.set_file(job.source, caption)

    def _show_after(self, job: FileJob) -> None:
        output = job.output
        if not output or not Path(output).exists():
            self.previews.after.clear("not converted yet")
            return
        shapes = job.info.get("shapes")
        caption = human_size(job.output_bytes or Path(output).stat().st_size)
        if shapes:
            caption = f"{shapes} shapes  -  {caption}"
        if job.source_bytes and job.output_bytes:
            change = job.output_bytes - job.source_bytes
            word = "heavier" if change > 0 else "lighter"
            caption += f"  ({human_size(abs(change))} {word})"
        self.previews.after.set_file(Path(output), caption)
