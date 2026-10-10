"""The "cut silences" screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`; what is here is the three
numbers that say what a silence is.
"""

from __future__ import annotations

import threading
from typing import Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QDoubleSpinBox, QGridLayout, QGroupBox, QLabel, QLineEdit, QSpinBox

from promak.core.batch import BatchEngine
from promak.core.dependencies import ffmpeg_exe
from promak.core.filejobs import FileJob
from promak.tools.silence.engine import ACCEPTED_EXTENSIONS, SilenceBatch, SilenceOptions
from promak.ui.file_panel import FileQueuePanel


class SilencePanel(FileQueuePanel):
    """Recordings in; the same recordings without their long pauses out."""

    TOOL_ID = "silence"
    PAGE_TITLE = "Cut silences"
    PAGE_SUBTITLE = (
        "Removes the silent parts from lectures, podcasts, voice notes and screen recordings, so they "
        "are quicker to listen to. A little of every pause is kept, so no word is clipped. Works on "
        "sound files and videos; your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Recordings"
    FILES_HINT = "Drag your recordings here.\nMP3, M4A, WAV, MP4, MKV, MOV..."
    FILE_DIALOG_FILTER = "Sound and video (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS) + ");;All files (*)"
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "recordings"
    DESTINATION_BOX_TITLE = "2 - Where to save the shorter recordings"
    OPTIONS_BOX_TITLE = "3 - What counts as silence"
    EXTRA_COLUMNS = ("Length", "Removed")
    EXTRA_COLUMN_WIDTH = 90
    START_LABEL = "Cut the silences"

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.level_spin = QSpinBox()
        self.level_spin.setRange(-80, -5)
        self.level_spin.setSuffix(" dB")
        self.level_spin.setToolTip("-35 dB suits a voice recorded close to the microphone. If too little is cut, "
                                   "raise it (-30); if quiet words are cut, lower it (-45).")
        self.length_spin = QDoubleSpinBox()
        self.length_spin.setRange(0.1, 60)
        self.length_spin.setSingleStep(0.1)
        self.length_spin.setDecimals(1)
        self.length_spin.setSuffix(" s")
        self.keep_spin = QDoubleSpinBox()
        self.keep_spin.setRange(0, 5)
        self.keep_spin.setSingleStep(0.05)
        self.keep_spin.setDecimals(2)
        self.keep_spin.setSuffix(" s on each side")
        self.suffix_input = QLineEdit()
        self.overwrite_check = QCheckBox("Replace files with the same name")
        hint = QLabel("Quieter than the level, and longer than the shortest silence, is cut. Videos come out as MP4.")
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        grid.addWidget(QLabel("Silence level"), 0, 0)
        grid.addWidget(self.level_spin, 0, 1)
        grid.addWidget(QLabel("Shortest silence"), 1, 0)
        grid.addWidget(self.length_spin, 1, 1)
        grid.addWidget(QLabel("Keep"), 2, 0)
        grid.addWidget(self.keep_spin, 2, 1)
        grid.addWidget(QLabel("Add to names"), 3, 0)
        grid.addWidget(self.suffix_input, 3, 1)
        grid.addWidget(self.overwrite_check, 4, 0, 1, 2)
        grid.addWidget(hint, 5, 0, 1, 2)

    def current_options(self) -> SilenceOptions:
        return SilenceOptions(threshold_db=self.level_spin.value(), min_silence=self.length_spin.value(),
                              keep=self.keep_spin.value(), suffix=self.suffix_input.text(),
                              overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        self.level_spin.setValue(int(c.get("silence.threshold_db", -35)))
        self.length_spin.setValue(float(c.get("silence.min_silence", 0.8)))
        self.keep_spin.setValue(float(c.get("silence.keep", 0.2)))
        self.suffix_input.setText(c.get("silence.suffix", " - no silences"))
        self.overwrite_check.setChecked(bool(c.get("silence.overwrite", False)))

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"silence.threshold_db": o.threshold_db, "silence.min_silence": o.min_silence,
                            "silence.keep": o.keep, "silence.suffix": o.suffix, "silence.overwrite": o.overwrite})

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return SilenceBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        if not ffmpeg_exe():
            return "FFmpeg is missing. Run install_windows.bat again, or:  pip install -U imageio-ffmpeg"
        return self.current_options().validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return (job.info.get("length", ""), job.info.get("removed", ""))
