"""The screen recorder screen.

Left: what to film (the whole screen or a rectangle dragged on it), how,
with or without the microphone, and where the videos go.  Middle: the
recordings made.  While recording, a small "Stop" button floats above
every window, so Promak itself can stay out of the picture.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QPoint, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from promak.core.dependencies import ffmpeg_exe
from promak.core.imaging import human_size
from promak.core.media import clock, media_facts
from promak.tools.screenrec.engine import (
    DDAGRAB,
    FRAME_RATES,
    GDIGRAB,
    IS_WINDOWS,
    QUALITIES,
    X11GRAB,
    Recorder,
    RecorderError,
    RecordOptions,
    Region,
    microphones,
    screen_size_text,
    wayland_session,
)
from promak.ui.plan_panel import PlanPanel, combo, folder_field, make_table, select

WHOLE = "whole"
AREA = "area"


class ScreenRecorderPanel(PlanPanel):
    """Film the screen, or a part of it, into an MP4."""

    TOOL_ID = "screenrec"
    PAGE_TITLE = "Screen recorder"
    PAGE_SUBTITLE = (
        "Films the whole screen or a rectangle of it - a tutorial, a bug to report, a call - into an "
        "MP4 that plays everywhere. Start, then Stop: a small button stays on top of every window "
        "while recording. Sound from the microphone is optional."
    )
    PREVIEW_TITLE = "Recordings"
    SCAN_LABEL = "Refresh"
    APPLY_LABEL = "Start recording"

    def __init__(self, parent=None) -> None:
        self.recorder: Optional[Recorder] = None
        self.region: Optional[Region] = None
        self.method_override = ""             # tests use the moving test picture
        self._made: List[Path] = []
        self._floating: Optional[_StopButton] = None
        super().__init__(parent)
        self.scan_button.setVisible(False)
        self._clock = QTimer(self)
        self._clock.setInterval(500)
        self._clock.timeout.connect(self._tick)
        if wayland_session():
            self.show_notice("This desktop uses Wayland, which does not let programs film the screen this way. "
                             "Log in with an X11 session to record.", "warning")
        elif not ffmpeg_exe():
            self.show_notice("FFmpeg is missing. Run install_windows.bat again, or:  pip install -U imageio-ffmpeg",
                             "warning")

    # ============================================================== setup
    def build_setup(self, layout: QVBoxLayout) -> None:
        box = QGroupBox("1 - What to film")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.area_combo = combo([("The whole screen", WHOLE), ("A rectangle I drag on the screen", AREA)])
        self.area_combo.currentIndexChanged.connect(self._on_area_changed)
        self.pick_button = QPushButton("Drag the rectangle...")
        self.pick_button.clicked.connect(self.pick_region)
        self.area_label = QLabel()
        self.area_label.setObjectName("HintLabel")
        self.area_label.setWordWrap(True)
        self.cursor_check = QCheckBox("Show the mouse pointer")
        grid.addWidget(QLabel("Film"), 0, 0)
        grid.addWidget(self.area_combo, 0, 1)
        grid.addWidget(self.pick_button, 1, 1)
        grid.addWidget(self.area_label, 2, 0, 1, 2)
        grid.addWidget(self.cursor_check, 3, 0, 1, 2)
        layout.addWidget(box)

        box = QGroupBox("2 - How")
        grid = QGridLayout(box)
        grid.setColumnStretch(1, 1)
        self.rate_combo = combo(FRAME_RATES)
        self.quality_combo = combo(QUALITIES)
        methods = [("Usual (works everywhere)", GDIGRAB), ("DirectX (lighter, Windows 8 or newer)", DDAGRAB)] \
            if IS_WINDOWS else [("X11 screen capture", X11GRAB)]
        self.method_combo = combo(methods)
        self.mic_combo = combo([("No sound (always works)", "")] + [(f"Microphone: {name}", name)
                                                                     for name in microphones()])
        self.mic_combo.setToolTip("Experimental: the microphone is reached through the system's own device names. "
                                  "If it cannot be opened, Promak says so and records without sound.")
        self.hide_check = QCheckBox("Minimise Promak while recording")
        grid.addWidget(QLabel("Smoothness"), 0, 0)
        grid.addWidget(self.rate_combo, 0, 1)
        grid.addWidget(QLabel("Quality"), 1, 0)
        grid.addWidget(self.quality_combo, 1, 1)
        grid.addWidget(QLabel("Capture"), 2, 0)
        grid.addWidget(self.method_combo, 2, 1)
        grid.addWidget(QLabel("Sound"), 3, 0)
        grid.addWidget(self.mic_combo, 3, 1)
        grid.addWidget(self.hide_check, 4, 0, 1, 2)
        note = QLabel("The microphone is experimental: device names differ from computer to computer. "
                      "Video without sound always works.")
        note.setObjectName("HintLabel")
        note.setWordWrap(True)
        grid.addWidget(note, 5, 0, 1, 2)
        layout.addWidget(box)

        box = QGroupBox("3 - Where the videos go")
        inner = QVBoxLayout(box)
        holder, self.folder_input = folder_field("Folder for the recordings", "Folder for the recordings")
        inner.addWidget(holder)
        layout.addWidget(box)

    def build_preview(self) -> QWidget:
        self.table = make_table(("Recording", "Length", "Size"), stretch=(0,))
        return self.table

    def preview_buttons(self):
        return (("Open folder", self._open_folder),)

    # =========================================================== settings
    def current_options(self) -> RecordOptions:
        screen = QGuiApplication.primaryScreen()
        whole = None
        if screen is not None:
            ratio = screen.devicePixelRatio()
            geometry = screen.geometry()
            whole = Region(int(geometry.x() * ratio), int(geometry.y() * ratio), int(geometry.width() * ratio),
                           int(geometry.height() * ratio))
        folder = self.folder_input.text().strip()
        return RecordOptions(
            folder=Path(folder) if folder else Path.home(),
            region=self.region if self.area_combo.currentData() == AREA else None, screen=whole,
            frame_rate=int(self.rate_combo.currentData() or 30), crf=int(self.quality_combo.currentData() or 23),
            method=self.method_override or self.method_combo.currentData() or "",
            microphone=self.mic_combo.currentData() or "", show_cursor=self.cursor_check.isChecked(),
        )

    def load_settings(self) -> None:
        from promak.core.paths import default_output_dir

        c = self.config
        select(self.area_combo, c.get("screenrec.area", WHOLE))
        saved = c.get("screenrec.region")
        if isinstance(saved, list) and len(saved) == 4:
            self.region = Region(*[int(v) for v in saved])
        self.cursor_check.setChecked(bool(c.get("screenrec.cursor", True)))
        select(self.rate_combo, int(c.get("screenrec.rate", 30)))
        select(self.quality_combo, int(c.get("screenrec.crf", 23)))
        select(self.method_combo, c.get("screenrec.method", GDIGRAB if IS_WINDOWS else X11GRAB))
        select(self.mic_combo, c.get("screenrec.microphone", ""))
        self.hide_check.setChecked(bool(c.get("screenrec.minimise", False)))
        self.folder_input.setText(c.get("screenrec.folder", "") or str(default_output_dir() / "Recordings"))
        self._on_area_changed()

    def save_settings(self) -> None:
        o = self.current_options()
        self.config.update({
            "screenrec.area": self.area_combo.currentData(), "screenrec.cursor": o.show_cursor,
            "screenrec.region": [self.region.x, self.region.y, self.region.width, self.region.height]
            if self.region else None,
            "screenrec.rate": o.frame_rate, "screenrec.crf": o.crf, "screenrec.method": self.method_combo.currentData(),
            "screenrec.microphone": o.microphone, "screenrec.minimise": self.hide_check.isChecked(),
            "screenrec.folder": str(o.folder),
        })

    def _on_area_changed(self, *_args) -> None:
        area = self.area_combo.currentData() == AREA
        self.pick_button.setVisible(area)
        self.area_label.setText(f"Films {screen_size_text(self.region if area else None)}."
                                + (" Drag the rectangle first." if area and not self.region else ""))
        self.refresh_buttons()

    # ============================================================== region
    def pick_region(self) -> None:
        self._picker = _RegionPicker()
        self._picker.picked.connect(self._region_picked)
        self._picker.showFullScreen()

    def _region_picked(self, rect: QRect) -> None:
        screen = QGuiApplication.primaryScreen()
        ratio = screen.devicePixelRatio() if screen is not None else 1.0
        self.region = Region(int(rect.x() * ratio), int(rect.y() * ratio), int(rect.width() * ratio),
                             int(rect.height() * ratio))
        self.save_settings()
        self._on_area_changed()

    # =========================================================== recording
    def can_apply(self) -> bool:
        if getattr(self, "recorder", None) is not None:
            return True
        return not (self.area_combo.currentData() == AREA and self.region is None) if hasattr(self, "area_combo") \
            else False

    def apply(self) -> None:
        if self.recorder is not None:
            self.stop()
            return
        options = self.current_options()
        try:
            self.recorder = Recorder(options)
            self.save_settings()
            self.recorder.start()
        except RecorderError as exc:
            self.recorder = None
            self.log("error", str(exc))
            from PySide6.QtWidgets import QMessageBox

            QMessageBox.warning(self, self.PAGE_TITLE, str(exc))
            return
        self.log("info", f"Recording {screen_size_text(options.region)}"
                         + (f" with {options.microphone}" if options.microphone else "") + "...")
        self._clock.start()
        self._floating = _StopButton()
        self._floating.stop_clicked.connect(self.stop)
        self._floating.show_near_corner()
        if self.hide_check.isChecked() and self.window() is not None:
            self.window().showMinimized()
        self._tick()

    def stop(self) -> None:
        if self.recorder is None:
            return
        self._clock.stop()
        if self._floating is not None:
            self._floating.close()
            self._floating = None
        recorder, self.recorder = self.recorder, None
        try:
            made = recorder.stop()
        except RecorderError as exc:
            self.log("error", str(exc))
            self._tick()
            return
        if self.window() is not None and self.window().isMinimized():
            self.window().showNormal()
        self._made.insert(0, made)
        self.log("info", f"Saved {made.name} ({clock(recorder.elapsed)}).")
        self._fill()
        self._tick()

    def _tick(self) -> None:
        if self.recorder is not None:
            text = f"Recording  {clock(self.recorder.elapsed)}"
            self.progress_bar.setFormat(text)
            self.progress_bar.setValue(1000)
            self.apply_button.setText("Stop recording")
            if self._floating is not None:
                self._floating.set_time(clock(self.recorder.elapsed))
            if not self.recorder.running:   # FFmpeg ended by itself (a screen unplugged...)
                self.stop()
        else:
            self.progress_bar.setFormat("Idle")
            self.progress_bar.setValue(0)
            self.apply_button.setText(self.APPLY_LABEL)
        self.refresh_buttons()

    def refresh_buttons(self) -> None:
        super().refresh_buttons()
        self.stop_button.setEnabled(getattr(self, "recorder", None) is not None)

    def _fill(self) -> None:
        self.table.setRowCount(0)
        for path in self._made:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(path.name))
            try:
                length = clock(media_facts(path).duration)
            except Exception:
                length = ""
            self.table.setItem(row, 1, QTableWidgetItem(length))
            self.table.setItem(row, 2, QTableWidgetItem(human_size(path.stat().st_size) if path.exists() else ""))

    def _open_folder(self) -> None:
        from promak.core.paths import open_in_file_manager

        folder = self.current_options().folder
        folder.mkdir(parents=True, exist_ok=True)
        open_in_file_manager(folder)

    # ------------------------------------------------------------ closing
    def shutdown(self) -> None:
        self.stop()
        super().shutdown()

    def has_running_work(self) -> bool:
        return self.recorder is not None


class _RegionPicker(QWidget):
    """A see-through sheet over the screen: drag a rectangle, Esc to cancel."""

    picked = Signal(QRect)

    def __init__(self) -> None:
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.CrossCursor)
        self._start: Optional[QPoint] = None
        self._end: Optional[QPoint] = None

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 90))
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(self.rect().adjusted(0, 40, 0, 0), Qt.AlignHCenter | Qt.AlignTop,
                         "Drag the rectangle to film - Esc to cancel")
        if self._start and self._end:
            rect = QRect(self._start, self._end).normalized()
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
            painter.setPen(QPen(QColor("#3A6BF0"), 2))
            painter.drawRect(rect)
            painter.drawText(rect.bottomLeft() + QPoint(4, 18), f"{rect.width()} x {rect.height()}")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self._start = self._end = event.position().toPoint()
        self.update()

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        self._end = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._end = event.position().toPoint()
        rect = QRect(self._start, self._end).normalized()
        self.close()
        if rect.width() > 15 and rect.height() > 15:
            self.picked.emit(rect.translated(self.geometry().topLeft()))

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape:
            self.close()


class _StopButton(QWidget):
    """The little window that stays above everything while recording."""

    stop_clicked = Signal()

    def __init__(self) -> None:
        super().__init__(None, Qt.Tool | Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("RecordingBadge")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        self.time_label = QLabel("0:00")
        button = QPushButton("Stop")
        button.setObjectName("DangerButton")
        button.clicked.connect(self.stop_clicked.emit)
        row.addWidget(QLabel("●"))
        row.addWidget(self.time_label)
        row.addWidget(button)

    def set_time(self, text: str) -> None:
        self.time_label.setText(text)

    def show_near_corner(self) -> None:
        screen = QGuiApplication.primaryScreen()
        self.adjustSize()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 24, area.top() + 24)
        self.show()
