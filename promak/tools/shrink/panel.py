"""The picture shrinker screen.

Queues, folders, drag and drop, progress and errors all come from
:class:`promak.ui.file_panel.FileQueuePanel`.  What is here is the options,
the before/after preview and the running total of what was saved.
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
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob, FileStage
from promak.core.imaging import ImageToolError, human_size, read_facts, saving_percent
from promak.tools.shrink.engine import ShrinkBatch, can_shrink
from promak.tools.shrink.models import (
    MAX_QUALITY,
    MIN_QUALITY,
    MODES,
    PNG_COLOUR_CHOICES,
    QUALITY_MODE,
    TARGET_MODE,
    TARGET_PRESETS,
    ShrinkOptions,
)
from promak.ui.file_panel import FileQueuePanel
from promak.ui.preview import PreviewPair

log = logging.getLogger(__name__)


def quality_in_words(quality: int) -> str:
    """Say what a quality number means, without using the number."""
    if quality >= 92:
        return "almost untouched - you will not see the difference"
    if quality >= 85:
        return "very good - safe for printing"
    if quality >= 78:
        return "good - the usual choice, much lighter and still sharp"
    if quality >= 68:
        return "fine for the web and for e-mail"
    if quality >= 55:
        return "light - small blurs appear on flat areas"
    return "very light - visibly softer, use it when size matters most"


class ShrinkPanel(FileQueuePanel):
    """Heavy pictures in, lighter pictures out - same format, same size."""

    TOOL_ID = "shrink"
    PAGE_TITLE = "Make pictures lighter"
    PAGE_SUBTITLE = (
        "Squeezes photographs and screenshots so they travel by e-mail and load fast on a "
        "website. The format never changes and the picture keeps its full size in pixels - "
        "only the file gets lighter."
    )
    FILES_BOX_TITLE = "1 - Pictures to make lighter"
    FILES_HINT = (
        "Drag your pictures here.\n"
        "JPG, PNG, WEBP and TIFF. Your originals are never touched."
    )
    DESTINATION_BOX_TITLE = "2 - Where to save the lighter copies"
    OPTIONS_BOX_TITLE = "3 - How much to squeeze"
    EXTRA_COLUMNS = ("Before", "After", "Saving")
    START_LABEL = "Make them lighter"
    RUNNING_LABEL = "Squeezing..."

    # ==================================================================
    # options
    # ==================================================================
    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        # --- which way ---------------------------------------------------
        self.mode_combo = QComboBox()
        for label, value in MODES:
            self.mode_combo.addItem(label, value)
        self.mode_combo.setToolTip(
            "Set the quality yourself when you know what you want.\n"
            'Choose "under a size" when something has a limit - an e-mail '
            "attachment, a web page, an upload form."
        )
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        grid.addWidget(QLabel("Way of working"), 0, 0)
        grid.addWidget(self.mode_combo, 0, 1, 1, 2)

        # --- quality -----------------------------------------------------
        self.quality_slider = QSlider(Qt.Horizontal)
        self.quality_slider.setRange(MIN_QUALITY, MAX_QUALITY)
        self.quality_slider.setSingleStep(1)
        self.quality_slider.setPageStep(5)
        self.quality_slider.setTickPosition(QSlider.TicksBelow)
        self.quality_slider.setTickInterval(10)
        self.quality_slider.valueChanged.connect(self._on_quality_changed)
        self.quality_label = QLabel()
        self.quality_label.setObjectName("HintLabel")
        self.quality_label.setWordWrap(True)
        self.quality_caption = QLabel("Quality")
        grid.addWidget(self.quality_caption, 1, 0)
        grid.addWidget(self.quality_slider, 1, 1)
        grid.addWidget(self.quality_label, 1, 2)

        # --- target size -------------------------------------------------
        self.target_combo = QComboBox()
        for label, value in TARGET_PRESETS:
            self.target_combo.addItem(label, value)
        self.target_combo.currentIndexChanged.connect(self._on_target_preset)
        self.target_spin = QSpinBox()
        self.target_spin.setRange(5, 100_000)
        self.target_spin.setSingleStep(50)
        self.target_spin.setSuffix(" KB")
        self.target_spin.setToolTip("The size each file must stay under, in kilobytes.")
        self.target_caption = QLabel("Stay under")
        grid.addWidget(self.target_caption, 2, 0)
        grid.addWidget(self.target_combo, 2, 1)
        grid.addWidget(self.target_spin, 2, 2)

        # --- PNG colours -------------------------------------------------
        self.png_combo = QComboBox()
        for label, value in PNG_COLOUR_CHOICES:
            self.png_combo.addItem(label, value)
        self.png_combo.setToolTip(
            "A PNG has no quality dial: it is squeezed by using fewer colours.\n"
            "Logos, icons and screenshots survive 64 or even 32 colours and get\n"
            "several times lighter. This setting does nothing to JPG files."
        )
        grid.addWidget(QLabel("PNG colours"), 3, 0)
        grid.addWidget(self.png_combo, 3, 1, 1, 2)

        # --- tick boxes --------------------------------------------------
        checks = QVBoxLayout()
        checks.setSpacing(4)
        self.metadata_check = QCheckBox("Remove hidden information (camera model, GPS position, date)")
        self.metadata_check.setToolTip(
            "Photographs carry hidden data, including where they were taken.\n"
            "Removing it makes the file a little lighter and stops you publishing\n"
            "your address by accident. The picture itself is unchanged."
        )
        self.overwrite_check = QCheckBox("Redo files that already exist")
        self.overwrite_check.setToolTip(
            "Off: a picture already shrunk in the destination folder is left alone.\n"
            "On: it is squeezed again and the old copy is replaced."
        )
        checks.addWidget(self.metadata_check)
        checks.addWidget(self.overwrite_check)
        grid.addLayout(checks, 4, 0, 1, 3)

        self.total_label = QLabel()
        self.total_label.setObjectName("SectionLabel")
        grid.addWidget(self.total_label, 5, 0, 1, 3)

    def build_extra_area(self) -> Optional[QWidget]:
        box = QGroupBox("Before and after")
        layout = QVBoxLayout(box)
        layout.setContentsMargins(12, 6, 12, 10)
        layout.setSpacing(8)
        self.previews = PreviewPair("Original", "Lighter copy")
        layout.addWidget(self.previews)
        hint = QLabel(
            "Select a row in the queue to compare the two pictures at the same size on "
            "screen. If you cannot see a difference, the saving was free."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return box

    # ==================================================================
    # settings
    # ==================================================================
    def current_options(self) -> ShrinkOptions:
        return ShrinkOptions(
            mode=self.mode_combo.currentData() or QUALITY_MODE,
            quality=int(self.quality_slider.value()),
            target_kb=int(self.target_spin.value()),
            png_colours=int(self.png_combo.currentData() or 0),
            strip_metadata=self.metadata_check.isChecked(),
            overwrite=self.overwrite_check.isChecked(),
        )

    def load_settings(self) -> None:
        super().load_settings()
        config = self.config
        index = self.mode_combo.findData(config.get("shrink.mode", QUALITY_MODE))
        self.mode_combo.setCurrentIndex(index if index >= 0 else 0)
        self.quality_slider.setValue(int(config.get("shrink.quality", 82) or 82))
        self.target_spin.setValue(int(config.get("shrink.target_kb", 500) or 500))
        colours = self.png_combo.findData(int(config.get("shrink.png_colours", 0) or 0))
        self.png_combo.setCurrentIndex(colours if colours >= 0 else 0)
        self.metadata_check.setChecked(bool(config.get("shrink.strip_metadata", True)))
        self.overwrite_check.setChecked(bool(config.get("shrink.overwrite", False)))
        self._on_quality_changed(self.quality_slider.value())
        self._on_mode_changed()
        self._refresh_total()

    def save_settings(self) -> None:
        super().save_settings()
        options = self.current_options()
        self.config.update(
            {
                "shrink.mode": options.mode,
                "shrink.quality": options.clamped_quality,
                "shrink.target_kb": int(options.target_kb),
                "shrink.png_colours": options.png_colours,
                "shrink.strip_metadata": options.strip_metadata,
                "shrink.overwrite": options.overwrite,
            }
        )

    def _on_mode_changed(self, *_args) -> None:
        target = (self.mode_combo.currentData() or QUALITY_MODE) == TARGET_MODE
        for widget in (self.quality_caption, self.quality_slider, self.quality_label):
            widget.setEnabled(not target)
        for widget in (self.target_caption, self.target_combo, self.target_spin):
            widget.setEnabled(target)

    def _on_quality_changed(self, value: int) -> None:
        self.quality_label.setText(f"{int(value)} - {quality_in_words(int(value))}")

    def _on_target_preset(self, *_args) -> None:
        value = self.target_combo.currentData()
        if value:
            self.target_spin.setValue(int(value))

    # ==================================================================
    # running
    # ==================================================================
    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return ShrinkBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        before = human_size(job.source_bytes) if job.source_bytes else ""
        after = human_size(job.output_bytes) if job.output_bytes else ""
        saving = ""
        if job.source_bytes and job.output_bytes:
            percent = saving_percent(job.source_bytes, job.output_bytes)
            saving = f"{percent:.0f}%" if percent > 0 else "-"
        return (before, after, saving)

    # ==================================================================
    # preview and totals
    # ==================================================================
    def on_job_selected(self, job: Optional[FileJob]) -> None:
        if job is None:
            self.previews.clear()
            return
        caption = human_size(job.source_bytes)
        try:
            facts = read_facts(job.source)
            caption = f"{facts.width} x {facts.height} - {facts.format} - {human_size(facts.file_bytes)}"
            allowed, reason = can_shrink(facts)
            self.show_notice("" if allowed else reason, "warning")
        except ImageToolError as exc:
            self.show_notice(str(exc), "error")
        self.previews.before.set_file(job.source, caption)
        self._show_after(job)

    def on_job_finished(self, job: FileJob) -> None:
        selected = self._selected_jobs()
        if not selected or selected[0].id == job.id:
            self._show_after(job)
        self._refresh_total()

    def _show_after(self, job: FileJob) -> None:
        output = job.output
        if not output or not Path(output).exists():
            message = "kept as it was" if job.stage is FileStage.SKIPPED else "not done yet"
            self.previews.after.clear(message)
            return
        percent = saving_percent(job.source_bytes, job.output_bytes)
        caption = human_size(job.output_bytes)
        if percent > 0:
            caption += f"  -  {percent:.0f}% lighter"
        self.previews.after.set_file(Path(output), caption)

    def _refresh_total(self) -> None:
        """One honest number: how much weight this run has actually saved."""
        before = sum(j.source_bytes for j in self._jobs if j.output_bytes)
        after = sum(j.output_bytes for j in self._jobs if j.output_bytes)
        if not before:
            self.total_label.setText("")
            return
        self.total_label.setText(
            f"Saved so far: {human_size(before - after)} "
            f"({saving_percent(before, after):.0f}% of {human_size(before)})"
        )
