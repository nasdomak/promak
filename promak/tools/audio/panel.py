"""The audio toolbox screen.

Queues, folders, drag and drop, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the options.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
)

from promak.core.batch import BatchEngine
from promak.core.dependencies import ffmpeg_exe
from promak.core.filejobs import FileJob
from promak.core.imaging import human_size
from promak.core.media import AUDIO_EXTENSIONS, VIDEO_EXTENSIONS
from promak.tools.audio.engine import (
    BITRATES,
    FORMAT_CHOICES,
    KEEP,
    LOUDNESS_CHOICES,
    AudioBatch,
    AudioOptions,
)
from promak.ui.file_panel import FileQueuePanel

_ALL = AUDIO_EXTENSIONS + VIDEO_EXTENSIONS


class AudioPanel(FileQueuePanel):
    """Sound files (or videos) in, converted / levelled / split sound out."""

    TOOL_ID = "audio"
    PAGE_TITLE = "Audio toolbox"
    PAGE_SUBTITLE = (
        "Converts sound files to the format you need, evens out the volume so every track "
        "plays at the same level, cuts the start and the end, and splits long recordings into "
        "pieces. Drop a video and you get its sound. Your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Sound files (or videos)"
    FILES_HINT = "Drag your sound files or videos here.\nMP3, M4A, WAV, FLAC, OGG, OPUS, MP4, MKV..."
    FILE_DIALOG_FILTER = (
        "Sound and video (" + " ".join(f"*{e}" for e in _ALL) + ");;All files (*)"
    )
    ACCEPTED_EXTENSIONS: Sequence[str] = _ALL
    ITEM_WORD = "sound files"
    DESTINATION_BOX_TITLE = "2 - Where to save the new files"
    OPTIONS_BOX_TITLE = "3 - What to do"
    EXTRA_COLUMNS = ("Size", "Result")
    START_LABEL = "Do it"

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        self.format_combo = QComboBox()
        for label, value in FORMAT_CHOICES:
            self.format_combo.addItem(label, value)
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(BITRATES)
        self.bitrate_combo.setToolTip("Higher = better sound and bigger file. 192k is plenty for music, 96k for speech.")
        self.loudness_combo = QComboBox()
        for label, value in LOUDNESS_CHOICES:
            self.loudness_combo.addItem(label, value)
        self.loudness_combo.setToolTip(
            "Makes quiet and loud tracks sound equally loud, the way radio stations do.\n"
            "Nothing is cut off: peaks are kept below the limit."
        )
        self.start_input = QLineEdit()
        self.start_input.setPlaceholderText("from the start")
        self.end_input = QLineEdit()
        self.end_input.setPlaceholderText("to the end")
        for widget in (self.start_input, self.end_input):
            widget.setToolTip("minutes:seconds, for example 1:30 - or hours:minutes:seconds")
        trim_row = QHBoxLayout()
        trim_row.addWidget(self.start_input)
        trim_row.addWidget(QLabel("to"))
        trim_row.addWidget(self.end_input)
        self.split_spin = QSpinBox()
        self.split_spin.setRange(0, 600)
        self.split_spin.setSuffix(" min pieces")
        self.split_spin.setSpecialValueText("one file, no pieces")
        self.mono_check = QCheckBox("Mono (one channel: half the size, fine for speech)")
        self.suffix_input = QLineEdit()
        self.suffix_input.setPlaceholderText("optional, for example  -level")
        self.overwrite_check = QCheckBox("Redo files that already exist")

        rows = (
            ("Format", self.format_combo), ("Quality", self.bitrate_combo),
            ("Volume", self.loudness_combo), ("Keep", trim_row), ("Split", self.split_spin),
            ("Add to names", self.suffix_input),
        )
        for index, (caption, widget) in enumerate(rows):
            grid.addWidget(QLabel(caption), index, 0)
            if isinstance(widget, QHBoxLayout):
                grid.addLayout(widget, index, 1)
            else:
                grid.addWidget(widget, index, 1)
        grid.addWidget(self.mono_check, len(rows), 0, 1, 2)
        grid.addWidget(self.overwrite_check, len(rows) + 1, 0, 1, 2)
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)

    def _on_format_changed(self, *_args) -> None:
        self.bitrate_combo.setEnabled((self.format_combo.currentData() or KEEP) not in ("wav", "flac"))

    def current_options(self) -> AudioOptions:
        return AudioOptions(
            output_format=self.format_combo.currentData() or KEEP,
            bitrate=self.bitrate_combo.currentText(),
            loudness=int(self.loudness_combo.currentData() or 0),
            start=self.start_input.text(),
            end=self.end_input.text(),
            split_minutes=self.split_spin.value(),
            mono=self.mono_check.isChecked(),
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
        self._select(self.format_combo, c.get("audio.format", "mp3"))
        index = self.bitrate_combo.findText(c.get("audio.bitrate", "192k"))
        self.bitrate_combo.setCurrentIndex(index if index >= 0 else 2)
        self._select(self.loudness_combo, int(c.get("audio.loudness", 0)))
        self.split_spin.setValue(int(c.get("audio.split_minutes", 0)))
        self.mono_check.setChecked(bool(c.get("audio.mono", False)))
        self.suffix_input.setText(c.get("audio.suffix", "") or "")
        self.overwrite_check.setChecked(bool(c.get("audio.overwrite", False)))
        self._on_format_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({
            "audio.format": o.output_format, "audio.bitrate": o.bitrate, "audio.loudness": o.loudness,
            "audio.split_minutes": o.split_minutes, "audio.mono": o.mono, "audio.suffix": o.suffix,
            "audio.overwrite": o.overwrite,
        })

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return AudioBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        if not ffmpeg_exe():
            return "FFmpeg is missing. Run install_windows.bat again, or:  pip install -U imageio-ffmpeg"
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (human_size(job.source_bytes) if job.source_bytes else "", job.info.get("result", ""))
