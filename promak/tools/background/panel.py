"""The "remove background" screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`, and so does the before/after
preview; what is here is the options and the note about the model.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QWidget

from promak.core.batch import BatchEngine
from promak.core.filejobs import FileJob
from promak.tools.background.engine import (
    ACCEPTED_EXTENSIONS,
    BACKGROUNDS,
    COLOUR,
    MODELS,
    TRANSPARENT,
    BackgroundBatch,
    BackgroundOptions,
    model_home,
    model_ready,
    model_size,
)
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import ColourField, combo, select
from promak.ui.preview import PreviewPair


class BackgroundPanel(FileQueuePanel):
    """Pictures in; the same pictures without their background out."""

    TOOL_ID = "background"
    PAGE_TITLE = "Remove the background"
    PAGE_SUBTITLE = (
        "Cuts out the person, product or animal of a picture and makes the background transparent, "
        "or a colour of your choice - for shop photos, ID pictures, presentations. It runs on this "
        "computer: the model is downloaded once, then works offline."
    )
    FILES_BOX_TITLE = "1 - Pictures"
    FILES_HINT = "Drag your pictures here.\nJPG, PNG, WEBP, TIFF..."
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    DESTINATION_BOX_TITLE = "2 - Where to save the cut-outs"
    OPTIONS_BOX_TITLE = "3 - How"
    EXTRA_COLUMNS = ("Result",)
    EXTRA_COLUMN_WIDTH = 120
    START_LABEL = "Remove the background"
    RUNNING_LABEL = "Working..."
    COMPONENTS = ("rembg", "onnxruntime")

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.model_combo = combo([(label, name) for label, name, _mb in MODELS])
        self.model_combo.currentIndexChanged.connect(self._show_model_state)
        self.model_label = QLabel()
        self.model_label.setObjectName("HintLabel")
        self.model_label.setWordWrap(True)
        self.background_combo = combo(BACKGROUNDS)
        self.background_combo.currentIndexChanged.connect(self._on_background_changed)
        self.colour_field = ColourField("#FFFFFF")
        self.format_combo = combo([("JPG", "JPEG"), ("PNG", "PNG")])
        self.edges_check = QCheckBox("Finer edges for hair and fur (slower)")
        self.crop_check = QCheckBox("Trim the picture to the subject")
        self.suffix_input = QLineEdit()
        self.overwrite_check = QCheckBox("Replace files with the same name")
        self.colour_caption = QLabel("Colour")
        self.format_caption = QLabel("Save as")
        grid.addWidget(QLabel("Model"), 0, 0)
        grid.addWidget(self.model_combo, 0, 1)
        grid.addWidget(self.model_label, 1, 0, 1, 2)
        grid.addWidget(QLabel("Background"), 2, 0)
        grid.addWidget(self.background_combo, 2, 1)
        grid.addWidget(self.colour_caption, 3, 0)
        grid.addWidget(self.colour_field, 3, 1)
        grid.addWidget(self.format_caption, 4, 0)
        grid.addWidget(self.format_combo, 4, 1)
        grid.addWidget(self.edges_check, 5, 0, 1, 2)
        grid.addWidget(self.crop_check, 6, 0, 1, 2)
        grid.addWidget(QLabel("Add to names"), 7, 0)
        grid.addWidget(self.suffix_input, 7, 1)
        grid.addWidget(self.overwrite_check, 8, 0, 1, 2)

    def build_extra_area(self) -> Optional[QWidget]:
        self.preview = PreviewPair("Before", "After")
        return self.preview

    def _show_model_state(self, *_args) -> None:
        model = self.model_combo.currentData() or MODELS[0][1]
        if model_ready(model):
            self.model_label.setText("Ready on this computer: works offline.")
        else:
            self.model_label.setText(f"Downloaded once, the first time it is used (about {model_size(model)} MB), "
                                     f"into {model_home()}. After that it works offline.")

    def _on_background_changed(self, *_args) -> None:
        colour = self.background_combo.currentData() == COLOUR
        for widget in (self.colour_caption, self.colour_field, self.format_caption, self.format_combo):
            widget.setVisible(colour)

    def current_options(self) -> BackgroundOptions:
        return BackgroundOptions(model=self.model_combo.currentData() or MODELS[0][1],
                                 background=self.background_combo.currentData() or TRANSPARENT,
                                 colour=self.colour_field.text(), colour_format=self.format_combo.currentData() or "JPEG",
                                 fine_edges=self.edges_check.isChecked(), crop=self.crop_check.isChecked(),
                                 suffix=self.suffix_input.text(), overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        select(self.model_combo, c.get("background.model", MODELS[0][1]))
        select(self.background_combo, c.get("background.background", TRANSPARENT))
        self.colour_field.setText(c.get("background.colour", "#FFFFFF"))
        select(self.format_combo, c.get("background.format", "JPEG"))
        self.edges_check.setChecked(bool(c.get("background.fine_edges", False)))
        self.crop_check.setChecked(bool(c.get("background.crop", False)))
        self.suffix_input.setText(c.get("background.suffix", "-no-background"))
        self.overwrite_check.setChecked(bool(c.get("background.overwrite", False)))
        self._show_model_state()
        self._on_background_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"background.model": o.model, "background.background": o.background,
                            "background.colour": o.colour, "background.format": o.colour_format,
                            "background.fine_edges": o.fine_edges, "background.crop": o.crop,
                            "background.suffix": o.suffix, "background.overwrite": o.overwrite})

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return BackgroundBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (job.info.get("size", ""),)

    def on_job_selected(self, job: Optional[FileJob]) -> None:
        if job is None:
            self.preview.clear()
            return
        self.preview.before.set_file(job.source, job.source.name)
        if job.output and job.output.exists():
            self.preview.after.set_file(job.output, job.output.name)
        else:
            self.preview.after.clear("not done yet")

    def on_job_finished(self, job: FileJob) -> None:
        self._show_model_state()
        selected = self._selected_jobs()
        if not selected or selected[0].id == job.id:
            self.on_job_selected(job)
