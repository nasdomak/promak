"""The "burn subtitles" screen.

Queues, folders, progress and errors come from
:class:`promak.ui.file_panel.FileQueuePanel`.  As soon as a video joins the
queue its subtitle file is looked for, and shown in the queue.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QWidget,
)

from promak.core.batch import BatchEngine
from promak.core.dependencies import ffmpeg_exe
from promak.core.filejobs import FileJob
from promak.tools.subtitles.engine import (
    ACCEPTED_EXTENSIONS,
    POSITIONS,
    QUALITIES,
    SIZES,
    SubtitleBatch,
    SubtitleOptions,
    find_subtitles,
)
from promak.ui.file_panel import FileQueuePanel
from promak.ui.plan_panel import ColourField, combo, select

AUTO = "auto"
CHOSEN = "file"


class SubtitlesPanel(FileQueuePanel):
    """Videos in; videos with the subtitles drawn into the picture out."""

    TOOL_ID = "subtitles"
    PAGE_TITLE = "Burn subtitles into a video"
    PAGE_SUBTITLE = (
        "Draws SRT or VTT subtitles - for example the transcripts of the video downloader - into "
        "the picture, so they show on every player, phone and social site. Size, place and outline "
        "are up to you. Your originals are never changed."
    )
    FILES_BOX_TITLE = "1 - Videos"
    FILES_HINT = ("Drag your videos here.\nTheir subtitles are found by themselves when they have the same name "
                  "(Lesson.mp4 + Lesson.srt).")
    FILE_DIALOG_FILTER = "Videos (" + " ".join(f"*{e}" for e in ACCEPTED_EXTENSIONS) + ");;All files (*)"
    ACCEPTED_EXTENSIONS: Sequence[str] = ACCEPTED_EXTENSIONS
    ITEM_WORD = "videos"
    DESTINATION_BOX_TITLE = "2 - Where to save the subtitled videos"
    OPTIONS_BOX_TITLE = "3 - Which subtitles, and how they look"
    EXTRA_COLUMNS = ("Subtitles", "Result")
    EXTRA_COLUMN_WIDTH = 110
    START_LABEL = "Burn the subtitles"
    RUNNING_LABEL = "Working..."

    def build_options(self, box: QGroupBox) -> None:
        grid = QGridLayout(box)
        grid.setContentsMargins(12, 6, 12, 8)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        self.source_combo = combo([("The file next to each video, with the same name", AUTO),
                                   ("This subtitle file, for every video", CHOSEN)])
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.file_holder = QWidget()
        row = QHBoxLayout(self.file_holder)
        row.setContentsMargins(0, 0, 0, 0)
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("an SRT, VTT or ASS file")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_subtitles)
        row.addWidget(self.file_input, 1)
        row.addWidget(browse)
        self.size_combo = combo(SIZES)
        self.position_combo = combo(POSITIONS)
        self.outline_spin = QSpinBox()
        self.outline_spin.setRange(0, 6)
        self.outline_spin.setToolTip("How thick the dark edge around the letters is: it keeps them readable on light scenes.")
        self.box_check = QCheckBox("A dark box behind the text instead of an outline")
        self.colour_field = ColourField("#FFFFFF")
        self.edge_field = ColourField("#000000")
        self.quality_combo = combo(QUALITIES)
        self.suffix_input = QLineEdit()
        self.overwrite_check = QCheckBox("Replace files with the same name")
        rows = (("Subtitles", self.source_combo), ("", self.file_holder), ("Text size", self.size_combo),
                ("Place", self.position_combo), ("Text colour", self.colour_field), ("Edge colour", self.edge_field),
                ("Outline", self.outline_spin))
        for index, (caption, widget) in enumerate(rows):
            if caption:
                grid.addWidget(QLabel(caption), index, 0)
            grid.addWidget(widget, index, 1)
        grid.addWidget(self.box_check, len(rows), 0, 1, 2)
        grid.addWidget(QLabel("Quality"), len(rows) + 1, 0)
        grid.addWidget(self.quality_combo, len(rows) + 1, 1)
        grid.addWidget(QLabel("Add to names"), len(rows) + 2, 0)
        grid.addWidget(self.suffix_input, len(rows) + 2, 1)
        grid.addWidget(self.overwrite_check, len(rows) + 3, 0, 1, 2)

    def _browse_subtitles(self) -> None:
        start = self.file_input.text().strip() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Subtitle file", start,
                                              "Subtitles (*.srt *.vtt *.ass *.ssa);;All files (*)")
        if path:
            self.file_input.setText(path)
            self._refresh_found()

    def _on_source_changed(self, *_args) -> None:
        self.file_holder.setVisible(self.source_combo.currentData() == CHOSEN)
        self._refresh_found()

    def _refresh_found(self) -> None:
        for job in getattr(self, "_jobs", []):
            job.info.pop("subtitles", None)
            self._refresh_row(job)

    def current_options(self) -> SubtitleOptions:
        chosen = self.file_input.text().strip() if self.source_combo.currentData() == CHOSEN else ""
        return SubtitleOptions(subtitle_file=Path(chosen) if chosen else None,
                               font_size=int(self.size_combo.currentData() or 20),
                               position=int(self.position_combo.currentData() or 2),
                               outline=self.outline_spin.value(), box=self.box_check.isChecked(),
                               colour=self.colour_field.text(), outline_colour=self.edge_field.text(),
                               crf=int(self.quality_combo.currentData() or 21), suffix=self.suffix_input.text(),
                               overwrite=self.overwrite_check.isChecked())

    def load_settings(self) -> None:
        super().load_settings()
        c = self.config
        select(self.source_combo, c.get("subtitles.source", AUTO))
        self.file_input.setText(c.get("subtitles.file", "") or "")
        select(self.size_combo, int(c.get("subtitles.size", 20)))
        select(self.position_combo, int(c.get("subtitles.position", 2)))
        self.outline_spin.setValue(int(c.get("subtitles.outline", 2)))
        self.box_check.setChecked(bool(c.get("subtitles.box", False)))
        self.colour_field.setText(c.get("subtitles.colour", "#FFFFFF"))
        self.edge_field.setText(c.get("subtitles.edge", "#000000"))
        select(self.quality_combo, int(c.get("subtitles.crf", 21)))
        self.suffix_input.setText(c.get("subtitles.suffix", " - subtitled"))
        self.overwrite_check.setChecked(bool(c.get("subtitles.overwrite", False)))
        self._on_source_changed()

    def save_settings(self) -> None:
        super().save_settings()
        o = self.current_options()
        self.config.update({"subtitles.source": self.source_combo.currentData(),
                            "subtitles.file": self.file_input.text().strip(), "subtitles.size": o.font_size,
                            "subtitles.position": o.position, "subtitles.outline": o.outline,
                            "subtitles.box": o.box, "subtitles.colour": o.colour, "subtitles.edge": o.outline_colour,
                            "subtitles.crf": o.crf, "subtitles.suffix": o.suffix, "subtitles.overwrite": o.overwrite})

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        return SubtitleBatch(self.current_options(), cancel_event=cancel_event)

    def validate_before_start(self) -> Optional[str]:
        if not ffmpeg_exe():
            return "FFmpeg is missing. Run install_windows.bat again, or:  pip install -U imageio-ffmpeg"
        options = self.current_options()
        if self.source_combo.currentData() == CHOSEN and not options.subtitle_file:
            return "Choose the subtitle file."
        return options.validate()

    def extra_values(self, job: FileJob) -> Sequence[str]:
        if "subtitles" not in job.info:
            chosen = self.current_options().subtitle_file if hasattr(self, "file_input") else None
            found = chosen or find_subtitles(job.source)
            job.info["subtitles"] = found.name if found else "none found"
        return (job.info.get("subtitles", ""), job.info.get("result", ""))
