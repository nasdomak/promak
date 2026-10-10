"""The video toolbox screen.

Queues, folders, drag and drop, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the options.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from promak.core.batch import BatchEngine
from promak.core.dependencies import ffmpeg_exe
from promak.core.filejobs import FileJob
from promak.core.imaging import human_size
from promak.core.media import VIDEO_EXTENSIONS
from promak.tools.videotools.engine import (
    HEIGHTS,
    JOB_CONVERT,
    JOB_COPY,
    JOB_FRAMES,
    JOB_TARGET,
    JOBS,
    QUALITIES,
    SIZE_PRESETS,
    VideoOptions,
    VideoToolsBatch,
)
from promak.ui.file_panel import FileQueuePanel


class VideoToolsPanel(FileQueuePanel):
    """Videos in; lighter, shorter or more compatible videos (or pictures) out."""

    TOOL_ID = "videotools"
    PAGE_TITLE = "Video toolbox"
    PAGE_SUBTITLE = (
        "Turns any video into an MP4 that plays on every device, makes it lighter or fits it "
        "under a size for e-mail and chat apps, keeps only the part you want, or takes pictures "
        "out of it. Your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Videos"
    FILES_HINT = "Drag your videos here.\nMP4, MOV, MKV, WEBM, AVI, WMV..."
    FILE_DIALOG_FILTER = "Videos (" + " ".join(f"*{e}" for e in VIDEO_EXTENSIONS) + ");;All files (*)"
    ACCEPTED_EXTENSIONS: Sequence[str] = VIDEO_EXTENSIONS
    ITEM_WORD = "videos"
    DESTINATION_BOX_TITLE = "2 - Where to save the results"
    OPTIONS_BOX_TITLE = "3 - What to do"
    EXTRA_COLUMNS = ("Size", "Result")
    START_LABEL = "Do it"

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self.job_combo = QComboBox()
        for label, value in JOBS:
            self.job_combo.addItem(label, value)
        self.quality_combo = QComboBox()
        for label, value in QUALITIES:
            self.quality_combo.addItem(label, value)
        self.height_combo = QComboBox()
        for label, value in HEIGHTS:
            self.height_combo.addItem(label, value)
        self.height_combo.setToolTip("Smaller videos are never enlarged.")
        self.size_spin = QSpinBox()
        self.size_spin.setRange(1, 100_000)
        self.size_spin.setSuffix(" MB")
        self.size_preset = QComboBox()
        self.size_preset.addItem("Ready-made sizes...", 0)
        for label, value in SIZE_PRESETS:
            self.size_preset.addItem(label, value)
        self.size_preset.activated.connect(self._on_size_preset)
        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.addWidget(self.size_spin)
        size_row.addWidget(self.size_preset, 1)
        size_holder = QWidget()
        size_holder.setLayout(size_row)
        self.every_spin = QDoubleSpinBox()
        self.every_spin.setRange(0.1, 3600)
        self.every_spin.setDecimals(1)
        self.every_spin.setSuffix(" s between pictures")
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("from the start")
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("to the end")
        for widget in (self.start_input, self.end_input):
            widget.setToolTip("minutes:seconds, for example 1:30 - or hours:minutes:seconds")
        trim_row = QHBoxLayout()
        trim_row.setContentsMargins(0, 0, 0, 0)
        trim_row.addWidget(self.start_input)
        trim_row.addWidget(QLabel("to"))
        trim_row.addWidget(self.end_input)
        trim_holder = QWidget()
        trim_holder.setLayout(trim_row)
        self.no_sound_check = QCheckBox("Remove the sound")
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("optional, for example  -light")
        self.overwrite_check = QCheckBox("Redo files that already exist")
        self.job_hint = QLabel()
        self.job_hint.setObjectName("HintLabel")
        self.job_hint.setWordWrap(True)

        self._rows = {}
        rows = (
            ("Job", self.job_combo, None), ("", self.job_hint, None),
            ("Quality", self.quality_combo, "quality"), ("Height", self.height_combo, "height"),
            ("Stay under", size_holder, "size"), ("Every", self.every_spin, "every"),
            ("Keep", trim_holder, None), ("Add to names", self.suffix_input, None),
        )
        for index, (caption, widget, key) in enumerate(rows):
            label = QLabel(caption)
            grid.addWidget(label, index, 0)
            grid.addWidget(widget, index, 1)
            if key:
                self._rows[key] = (label, widget)
        grid.addWidget(self.no_sound_check, len(rows), 0, 1, 2)
        grid.addWidget(self.overwrite_check, len(rows) + 1, 0, 1, 2)
        self.job_combo.currentIndexChanged.connect(self._on_job_changed)

    _HINTS = {
        JOB_CONVERT: "H.264 video and AAC sound: opens on phones, TVs and every player. "
                     "A lower quality or height makes the file lighter.",
        JOB_TARGET: "The quality is chosen for you so the file stays under the size.",
        JOB_COPY: "Nothing is re-encoded, so it takes seconds and loses nothing; the cut "
                  "moves to the nearest key frame (up to a few seconds).",
        JOB_FRAMES: "One JPG picture every few seconds, in a folder named after the video.",
    }
    _VISIBLE = {
        JOB_CONVERT: {"quality", "height"},
        JOB_TARGET: {"size", "height"},
        JOB_COPY: set(),
        JOB_FRAMES: {"every"},
    }

    def _on_job_changed(self, *_args) -> None:
        job = self.job_combo.currentData() or JOB_CONVERT
        self.job_hint.setText(self._HINTS[job])
        for key, widgets in self._rows.items():
            for widget in widgets:
                widget.setVisible(key in self._VISIBLE[job])
        self.no_sound_check.setVisible(job != JOB_FRAMES)

    def _on_size_preset(self, index: int) -> None:
        value = self.size_preset.itemData(index)
        if value:
            self.size_spin.setValue(int(value))
        self.size_preset.setCurrentIndex(0)

    def current_options(self) -> VideoOptions:
        return VideoOptions(
            job=self.job_combo.currentData() or JOB_CONVERT,
            crf=int(self.quality_combo.currentData() or 22),
            max_height=int(self.height_combo.currentData() or 0),
            target_mb=self.size_spin.value(),
            start=self.start_input.text(),
            end=self.end_input.text(),
            no_sound=self.no_sound_check.isChecked(),
            frame_every=self.every_spin.value(),
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
        self._select(self.job_combo, c.get("videotools.job", JOB_CONVERT))
        self._select(self.quality_combo, int(c.get("videotools.crf", 22)))
        self._select(self.height_combo, int(c.get("videotools.max_height", 0)))
        self.size_spin.setValue(int(c.get("videotools.target_mb", 25)))
        self.every_spin.setValue(float(c.get("videotools.frame_every", 5.0)))
        self.no_sound_check.setChecked(bool(c.get("videotools.no_sound", False)))
        self.suffix_input.setText(c.get("videotools.suffix", "") or "")
        self.overwrite_check.setChecked(bool(c.get("videotools.overwrite", False)))
        self._on_job_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({
            "videotools.job": o.job, "videotools.crf": o.crf, "videotools.max_height": o.max_height,
            "videotools.target_mb": o.target_mb, "videotools.frame_every": o.frame_every,
            "videotools.no_sound": o.no_sound, "videotools.suffix": o.suffix,
            "videotools.overwrite": o.overwrite,
        })

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return VideoToolsBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        if not ffmpeg_exe():
            return "FFmpeg is missing. Run install_windows.bat again, or:  pip install -U imageio-ffmpeg"
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (human_size(job.source_bytes) if job.source_bytes else "", job.info.get("result", ""))
