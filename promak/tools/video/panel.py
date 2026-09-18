"""The video downloader screen.

Works with any site the download engine knows, not only YouTube.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from promak.core.config import get_config
from promak.core.dependencies import (
    SUBPROCESS_QUIET,
    check_dependencies,
    missing_dependencies,
    refresh as refresh_dependencies,
)
from promak.core.paths import default_output_dir, open_in_file_manager
from promak.tools.video import downloader
from promak.tools.video.layout import LAYOUT_CHOICES, SORTED, normalise_mode
from promak.tools.video.models import (
    COOKIE_BROWSERS,
    LANGUAGES,
    MP3_BITRATES,
    VIDEO_QUALITIES,
    WHISPER_MODEL_SIZES,
    WHISPER_MODELS,
    Job,
    JobOptions,
    Stage,
    extract_urls,
    KNOWN_SITES_HINT,
    looks_like_video_url,
)
from promak.tools.video.worker import PipelineWorker

log = logging.getLogger(__name__)

COL_NAME, COL_FOLDER, COL_STEP, COL_PROGRESS, COL_DETAIL = range(5)


class _PlaylistExpander(QThread):
    """Resolves a playlist or channel URL into single video URLs."""

    resolved = Signal(str, list)
    failed = Signal(str, str)

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self._url = url

    def run(self) -> None:  # noqa: D102
        try:
            entries = downloader.expand_playlist(self._url)
        except Exception as exc:
            self.failed.emit(self._url, str(exc))
            return
        items = []
        for entry in entries:
            url = entry.get("webpage_url") or entry.get("original_url") or entry.get("url") or ""
            if url and not url.startswith("http"):
                # Only YouTube hands back a bare video id; on any other site an
                # entry without a full address is unusable, so it is dropped.
                url = (
                    f"https://www.youtube.com/watch?v={url}"
                    if "youtu" in self._url.lower()
                    else ""
                )
            if url:
                items.append({"url": url, "title": entry.get("title") or ""})
        self.resolved.emit(self._url, items)


class _Updater(QThread):
    """Runs ``pip install -U yt-dlp`` without freezing the window."""

    done = Signal(bool, str)

    def run(self) -> None:  # noqa: D102
        command = [sys.executable, "-m", "pip", "install", "-U", "yt-dlp"]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=600,
                **SUBPROCESS_QUIET,
            )
        except Exception as exc:
            self.done.emit(False, str(exc))
            return
        output = ((result.stdout or "") + (result.stderr or "")).strip()
        tail = "\n".join(output.splitlines()[-6:])
        self.done.emit(result.returncode == 0, tail)


class VideoPanel(QWidget):
    """Paste links, choose folders, convert."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.config = get_config()
        self._jobs: List[Job] = []
        self._rows: Dict[int, int] = {}          # job id -> table row
        self._bars: Dict[int, QProgressBar] = {}  # job id -> progress bar
        self._worker: Optional[PipelineWorker] = None
        self._updater: Optional[_Updater] = None
        self._expanders: List[_PlaylistExpander] = []

        self._build_ui()
        self._load_settings()
        self._refresh_dependency_banner()
        self._update_buttons()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 18, 22, 16)
        outer.setSpacing(12)

        title = QLabel("Video downloader")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Download a video from almost any site, extract the MP3 and transcribe the audio - "
            "one link or a whole list."
        )
        subtitle.setObjectName("PageSubtitle")
        outer.addWidget(title)
        outer.addWidget(subtitle)

        status_row = QHBoxLayout()
        self.component_label = QLabel()
        self.component_label.setObjectName("HintLabel")
        self.component_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        check_button = QPushButton("Check components")
        check_button.setToolTip("Look again for yt-dlp, FFmpeg and the transcription engine.")
        check_button.clicked.connect(self._check_components)
        self.update_button = QPushButton("Update yt-dlp")
        self.update_button.setToolTip(
            "Video sites change often. When downloads start failing for every video,\n"
            "updating the download engine is almost always the fix."
        )
        self.update_button.clicked.connect(self._update_yt_dlp)
        status_row.addWidget(self.component_label, 1)
        status_row.addWidget(check_button)
        status_row.addWidget(self.update_button)
        outer.addLayout(status_row)

        self.dependency_banner = QLabel()
        self.dependency_banner.setObjectName("HintLabel")
        self.dependency_banner.setWordWrap(True)
        self.dependency_banner.setVisible(False)
        self.dependency_banner.setFrameShape(QFrame.StyledPanel)
        self.dependency_banner.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outer.addWidget(self.dependency_banner)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_setup_area())
        splitter.addWidget(self._build_queue_area())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([420, 460])
        outer.addWidget(splitter, 1)

        outer.addLayout(self._build_footer())

    def _build_setup_area(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 6, 0)
        layout.setSpacing(12)

        # --- 1. links ---------------------------------------------------
        links_box = QGroupBox("1 - Video links")
        links_layout = QVBoxLayout(links_box)
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(
            "Paste one or more links to videos, one per line - any site.\n"
            "https://www.youtube.com/watch?v=...     https://vimeo.com/...\n"
            "https://www.facebook.com/...            https://a-news-site.com/article-with-video"
        )
        self.url_input.setToolTip(f"Works with {KNOWN_SITES_HINT}.")
        self.url_input.setFixedHeight(92)
        links_layout.addWidget(self.url_input)

        links_buttons = QHBoxLayout()
        self.expand_playlists = QCheckBox("Split playlists into single videos")
        self.expand_playlists.setToolTip(
            "When a link points to a playlist or a channel, add every video it contains."
        )
        paste_button = QPushButton("Paste from clipboard")
        paste_button.clicked.connect(self._paste_from_clipboard)
        add_button = QPushButton("Add to queue")
        add_button.setObjectName("PrimaryButton")
        add_button.clicked.connect(self._add_urls)
        links_buttons.addWidget(self.expand_playlists)
        links_buttons.addStretch(1)
        links_buttons.addWidget(paste_button)
        links_buttons.addWidget(add_button)
        links_layout.addLayout(links_buttons)
        layout.addWidget(links_box)

        # --- 2. destination --------------------------------------------
        dest_box = QGroupBox("2 - Destination folder")
        dest_layout = QVBoxLayout(dest_box)
        row = QHBoxLayout()
        self.destination_input = QLineEdit()
        self.destination_input.setPlaceholderText("Folder where the files will be saved")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_destination)
        row.addWidget(self.destination_input, 1)
        row.addWidget(browse)
        dest_layout.addLayout(row)
        hint = QLabel(
            "This folder is used for every link you add next. "
            "To send some videos somewhere else, select their rows in the queue "
            "and use \"Change folder\" - general, specific or mixed all work."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        dest_layout.addWidget(hint)

        layout_row = QHBoxLayout()
        layout_label = QLabel("Arrange the files")
        self.layout_combo = QComboBox()
        for label, value in LAYOUT_CHOICES:
            self.layout_combo.addItem(label, value)
        self.layout_combo.setToolTip(
            "With the recommended arrangement each video gets its own folder,\n"
            "and inside it one folder per kind of file:\n\n"
            "    Destination\\Video title\\mp4\\Video title.mp4\n"
            "    Destination\\Video title\\mp3\\Video title.mp3\n"
            "    Destination\\Video title\\transcript\\Video title.txt\n\n"
            "Ten links then give ten tidy folders instead of thirty files in a heap."
        )
        self.layout_combo.currentIndexChanged.connect(self._on_layout_changed)
        layout_row.addWidget(layout_label)
        layout_row.addWidget(self.layout_combo, 1)
        dest_layout.addLayout(layout_row)

        self.layout_preview = QLabel()
        self.layout_preview.setObjectName("HintLabel")
        self.layout_preview.setWordWrap(True)
        dest_layout.addWidget(self.layout_preview)
        layout.addWidget(dest_box)

        # --- 3. options -------------------------------------------------
        options_box = QGroupBox("3 - What to produce")
        grid = QGridLayout(options_box)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(9)

        self.keep_video_check = QCheckBox("Keep the video (MP4)")
        self.make_mp3_check = QCheckBox("Extract the audio (MP3)")
        self.transcribe_check = QCheckBox("Transcribe the audio")
        for widget in (self.keep_video_check, self.make_mp3_check, self.transcribe_check):
            widget.toggled.connect(self._on_options_changed)
        grid.addWidget(self.keep_video_check, 0, 0)
        grid.addWidget(self.make_mp3_check, 0, 1)
        grid.addWidget(self.transcribe_check, 0, 2)

        self.quality_combo = QComboBox()
        self.quality_combo.addItems(VIDEO_QUALITIES)
        grid.addWidget(QLabel("Video quality"), 1, 0)
        grid.addWidget(self.quality_combo, 2, 0)

        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(MP3_BITRATES)
        grid.addWidget(QLabel("MP3 quality"), 1, 1)
        grid.addWidget(self.bitrate_combo, 2, 1)

        self.model_combo = QComboBox()
        for name in WHISPER_MODELS:
            self.model_combo.addItem(f"{name}  ({WHISPER_MODEL_SIZES[name]})", name)
        self.model_combo.currentIndexChanged.connect(self._on_options_changed)
        grid.addWidget(QLabel("Transcription model"), 1, 2)
        grid.addWidget(self.model_combo, 2, 2)

        self.language_combo = QComboBox()
        for code, label in LANGUAGES.items():
            self.language_combo.addItem(label, code)
        grid.addWidget(QLabel("Spoken language"), 3, 0)
        grid.addWidget(self.language_combo, 4, 0)

        formats = QHBoxLayout()
        self.txt_check = QCheckBox("Transcript .txt")
        self.srt_check = QCheckBox("Subtitles .srt")
        formats.addWidget(self.txt_check)
        formats.addWidget(self.srt_check)
        formats.addStretch(1)
        grid.addWidget(QLabel("Transcript files"), 3, 1, 1, 2)
        grid.addLayout(formats, 4, 1, 1, 2)

        self.cookies_combo = QComboBox()
        for code, label in COOKIE_BROWSERS.items():
            self.cookies_combo.addItem(label, code)
        self.cookies_combo.setToolTip(
            "Some sites ask for a signed-in session (age-restricted videos, or\n"
            "when it suspects automated traffic). Pick the browser where you are logged\n"
            "in to that site and Promak will borrow its cookies."
        )
        cookies_label = QLabel("Use cookies from")
        cookies_label.setToolTip(self.cookies_combo.toolTip())
        grid.addWidget(cookies_label, 5, 0)
        grid.addWidget(self.cookies_combo, 6, 0)

        self.compatible_check = QCheckBox("Play on any device (H.264)")
        self.compatible_check.setToolTip(
            "The best streams on YouTube and other big sites use VP9 or AV1. They save\n"
            "space, but the players\n"
            "built into Windows often show a few seconds and then freeze the picture\n"
            "while the sound carries on. With this ticked Promak asks for H.264, which\n"
            "opens everywhere. Untick it only if you want the smallest file and your\n"
            "player handles modern codecs."
        )
        self.compatible_check.toggled.connect(self._on_options_changed)
        grid.addWidget(self.compatible_check, 5, 1, 1, 2)

        self.overwrite_check = QCheckBox("Redo files that already exist")
        grid.addWidget(self.overwrite_check, 6, 1, 1, 2)

        self.options_hint = QLabel()
        self.options_hint.setObjectName("HintLabel")
        self.options_hint.setWordWrap(True)
        grid.addWidget(self.options_hint, 7, 0, 1, 3)
        layout.addWidget(options_box)

        layout.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _build_queue_area(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(8)

        header = QHBoxLayout()
        label = QLabel("Queue")
        label.setObjectName("SectionLabel")
        header.addWidget(label)
        header.addStretch(1)
        for text, slot in (
            ("Change folder", self._change_folder_for_selection),
            ("Open folder", self._open_selected_folder),
            ("Retry failed", self._retry_failed),
            ("Remove selected", self._remove_selected),
            ("Clear finished", self._clear_finished),
        ):
            button = QPushButton(text)
            button.clicked.connect(slot)
            header.addWidget(button)
        layout.addLayout(header)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Video", "Destination", "Step", "Progress", "Details"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header_view = self.table.horizontalHeader()
        header_view.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        header_view.setSectionResizeMode(COL_FOLDER, QHeaderView.Interactive)
        header_view.setSectionResizeMode(COL_STEP, QHeaderView.ResizeToContents)
        header_view.setSectionResizeMode(COL_PROGRESS, QHeaderView.Fixed)
        header_view.setSectionResizeMode(COL_DETAIL, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_FOLDER, 220)
        self.table.setColumnWidth(COL_PROGRESS, 130)
        self.table.setColumnWidth(COL_DETAIL, 220)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table, 1)

        log_label = QLabel("Activity")
        log_label.setObjectName("SectionLabel")
        layout.addWidget(log_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setFixedHeight(120)
        layout.addWidget(self.log_view)
        return container

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setFormat("Idle")
        footer.addWidget(self.overall_bar, 1)

        self.start_button = QPushButton("Start conversion")
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.setMinimumWidth(160)
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.clicked.connect(self._stop)
        footer.addWidget(self.start_button)
        footer.addWidget(self.stop_button)
        return footer

    # ------------------------------------------------------------ settings
    def _load_settings(self) -> None:
        config = self.config
        destination = config.get("video.default_destination") or str(default_output_dir())
        self.destination_input.setText(destination)
        self.keep_video_check.setChecked(bool(config.get("video.keep_video")))
        self.make_mp3_check.setChecked(bool(config.get("video.make_mp3")))
        self.transcribe_check.setChecked(bool(config.get("video.transcribe")))
        self.txt_check.setChecked(bool(config.get("video.write_txt")))
        self.srt_check.setChecked(bool(config.get("video.write_srt")))
        self._select_data(self.layout_combo, normalise_mode(config.get("video.folder_layout", SORTED)))
        self.compatible_check.setChecked(bool(config.get("video.compatible_video", True)))
        self.overwrite_check.setChecked(bool(config.get("video.overwrite")))
        self._select_text(self.quality_combo, config.get("video.video_quality"))
        self._select_text(self.bitrate_combo, config.get("video.mp3_bitrate"))
        self._select_data(self.model_combo, config.get("video.whisper_model"))
        self._select_data(self.language_combo, config.get("video.language"))
        self._select_data(self.cookies_combo, config.get("video.cookies_from_browser", ""))
        self._on_layout_changed()
        self._on_options_changed()

    def save_settings(self) -> None:
        self.config.update(
            {
                "video.default_destination": self.destination_input.text().strip(),
                "video.keep_video": self.keep_video_check.isChecked(),
                "video.make_mp3": self.make_mp3_check.isChecked(),
                "video.transcribe": self.transcribe_check.isChecked(),
                "video.write_txt": self.txt_check.isChecked(),
                "video.write_srt": self.srt_check.isChecked(),
                "video.folder_layout": self.layout_combo.currentData() or SORTED,
                "video.compatible_video": self.compatible_check.isChecked(),
                "video.overwrite": self.overwrite_check.isChecked(),
                "video.video_quality": self.quality_combo.currentText(),
                "video.mp3_bitrate": self.bitrate_combo.currentText(),
                "video.whisper_model": self.model_combo.currentData(),
                "video.language": self.language_combo.currentData(),
                "video.cookies_from_browser": self.cookies_combo.currentData() or "",
            }
        )

    def _on_layout_changed(self, *_args) -> None:
        """Show in plain words where the files of one video will end up."""
        mode = self.layout_combo.currentData() or SORTED
        folder = Path(self.destination_input.text().strip() or "Destination").name or "Destination"
        if mode == SORTED:
            text = (
                f"Example:  {folder}\\Video title\\mp4\\Video title.mp4  -  "
                f"...\\mp3\\Video title.mp3  -  ...\\transcript\\Video title.txt"
            )
        elif mode == "per_video":
            text = f"Example:  {folder}\\Video title\\Video title.mp4 (and .mp3, .txt, .srt)"
        else:
            text = f"Example:  {folder}\\Video title.mp4 (and .mp3, .txt, .srt), all side by side"
        self.layout_preview.setText(text)

    @staticmethod
    def _select_text(combo: QComboBox, value) -> None:
        index = combo.findText(str(value))
        combo.setCurrentIndex(index if index >= 0 else 0)

    @staticmethod
    def _select_data(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _current_options(self) -> JobOptions:
        return JobOptions(
            keep_video=self.keep_video_check.isChecked(),
            make_mp3=self.make_mp3_check.isChecked(),
            transcribe=self.transcribe_check.isChecked(),
            video_quality=self.quality_combo.currentText(),
            mp3_bitrate=self.bitrate_combo.currentText(),
            whisper_model=self.model_combo.currentData() or "small",
            language=self.language_combo.currentData() or "auto",
            write_txt=self.txt_check.isChecked(),
            write_srt=self.srt_check.isChecked(),
            folder_layout=self.layout_combo.currentData() or SORTED,
            overwrite=self.overwrite_check.isChecked(),
            cookies_from_browser=self.cookies_combo.currentData() or "",
            compatible_video=self.compatible_check.isChecked(),
        )

    def _on_options_changed(self, *_args) -> None:
        transcribing = self.transcribe_check.isChecked()
        self.quality_combo.setEnabled(self.keep_video_check.isChecked())
        self.bitrate_combo.setEnabled(self.make_mp3_check.isChecked())
        self.model_combo.setEnabled(transcribing)
        self.language_combo.setEnabled(transcribing)
        self.txt_check.setEnabled(transcribing)
        self.srt_check.setEnabled(transcribing)

        self.compatible_check.setEnabled(self.keep_video_check.isChecked())

        messages = []
        if not self.keep_video_check.isChecked():
            messages.append("Only the audio stream is downloaded, which is much faster.")
        elif not self.compatible_check.isChecked():
            messages.append(
                "Best-quality streams may use VP9 or AV1: smaller files, but some "
                "Windows players freeze the picture."
            )
        if transcribing:
            model = self.model_combo.currentData() or "small"
            messages.append(
                f"The '{model}' model runs on this computer for free; "
                "it is downloaded once on the first run."
            )
        self.options_hint.setText("  ".join(messages))
        self._update_buttons()

    def _refresh_dependency_banner(self) -> None:
        components = check_dependencies()
        self.component_label.setText(
            "Components:  "
            + "   ".join(f"{d.label} {'OK' if d.available else 'MISSING'}" for d in components)
        )
        self.component_label.setToolTip(
            "\n".join(f"{d.label}: {d.detail or ('not found' if not d.available else 'available')}"
                      for d in components)
        )

        missing = [d for d in components if not d.available]
        if not missing:
            self.dependency_banner.setVisible(False)
            return
        lines = ["Some components are missing, so part of the pipeline is unavailable:"]
        for dependency in missing:
            lines.append(f"  - {dependency.label} (needed for {dependency.required_for})")
        lines.append("")
        lines.append("Install them with:  pip install -U " + " ".join(d.pip_name for d in missing))
        self.dependency_banner.setText("\n".join(lines))
        self.dependency_banner.setVisible(True)

    def _check_components(self) -> None:
        """Look for the components again and report what was found."""
        refresh_dependencies()
        self._refresh_dependency_banner()
        components = check_dependencies()
        details = "\n".join(
            f"{'[OK]     ' if d.available else '[MISSING]'} {d.label}"
            + (f"\n              {d.detail}" if d.detail else "")
            for d in components
        )
        for dependency in components:
            self._log(
                "info" if dependency.available else "error",
                f"{dependency.label}: {dependency.detail or ('found' if dependency.available else 'not found')}",
            )
        QMessageBox.information(self, "Components", details)

    def _update_yt_dlp(self) -> None:
        """Update the download engine, the usual cure when a site changes."""
        self.update_button.setEnabled(False)
        self.update_button.setText("Updating...")
        self._log("info", "Updating yt-dlp, please wait...")
        self._updater = _Updater(self)
        self._updater.done.connect(self._on_update_finished)
        self._updater.start()

    def _on_update_finished(self, ok: bool, output: str) -> None:
        self.update_button.setEnabled(True)
        self.update_button.setText("Update yt-dlp")
        self._log("info" if ok else "error", output or ("Updated." if ok else "Update failed."))
        refresh_dependencies()
        self._refresh_dependency_banner()
        QMessageBox.information(
            self,
            "Update",
            ("yt-dlp was updated.\nRestart Promak so the new version is used.\n\n" if ok
             else "The update failed.\n\n") + (output or ""),
        )

    # -------------------------------------------------------------- queue
    def _paste_from_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if not text.strip():
            return
        existing = self.url_input.toPlainText()
        self.url_input.setPlainText((existing + "\n" + text).strip() if existing.strip() else text.strip())

    def _add_urls(self) -> None:
        raw = self.url_input.toPlainText()
        urls = extract_urls(raw)
        if not urls:
            QMessageBox.information(
                self, "No links found", "Paste at least one link starting with http."
            )
            return

        destination = self._validated_destination()
        if destination is None:
            return

        if self.expand_playlists.isChecked():
            playlists = [u for u in urls if "list=" in u or "/playlist" in u or "/@" in u]
            singles = [u for u in urls if u not in playlists]
            self._append_jobs(singles, destination)
            for url in playlists:
                self._log("info", f"Reading playlist {url} ...")
                expander = _PlaylistExpander(url, self)
                expander.resolved.connect(
                    lambda source, items, folder=destination: self._on_playlist_resolved(source, items, folder)
                )
                expander.failed.connect(self._on_playlist_failed)
                expander.finished.connect(lambda e=expander: self._expanders.remove(e) if e in self._expanders else None)
                self._expanders.append(expander)
                expander.start()
        else:
            self._append_jobs(urls, destination)

        self.url_input.clear()

    def _on_playlist_resolved(self, source: str, items: List[Dict], destination: Path) -> None:
        if not items:
            self._log("warning", f"No videos found in {source}.")
            return
        self._log("info", f"Playlist resolved: {len(items)} video(s).")
        self._append_jobs([item["url"] for item in items], destination,
                          titles=[item.get("title", "") for item in items])

    def _on_playlist_failed(self, source: str, error: str) -> None:
        self._log("error", f"Could not read {source}: {error}")
        self._append_jobs([source], Path(self.destination_input.text().strip()))

    def _append_jobs(self, urls: List[str], destination: Path, titles: Optional[List[str]] = None) -> None:
        added = 0
        known = {job.url for job in self._jobs}
        for index, url in enumerate(urls):
            if url in known:
                self._log("info", f"Already in the queue, skipped: {url}")
                continue
            job = Job(url=url, destination=destination)
            if titles and index < len(titles):
                job.title = titles[index] or ""
            if not looks_like_video_url(url):
                self._log(
                    "warning",
                    f"This does not look like a web address, so it will probably fail: {url}",
                )
            self._jobs.append(job)
            known.add(url)
            self._add_row(job)
            added += 1
        if added:
            self._log("info", f"Added {added} link(s) to the queue.")
        self._update_buttons()

    def _add_row(self, job: Job) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[job.id] = row

        name_item = QTableWidgetItem(job.display_name)
        name_item.setToolTip(job.url)
        name_item.setData(Qt.UserRole, job.id)
        self.table.setItem(row, COL_NAME, name_item)

        folder_item = QTableWidgetItem(str(job.destination))
        folder_item.setToolTip(str(job.destination))
        self.table.setItem(row, COL_FOLDER, folder_item)

        self.table.setItem(row, COL_STEP, QTableWidgetItem(job.stage.value))

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        bar.setFormat("%p%")
        self.table.setCellWidget(row, COL_PROGRESS, bar)
        self._bars[job.id] = bar

        self.table.setItem(row, COL_DETAIL, QTableWidgetItem(""))

    def _selected_jobs(self) -> List[Job]:
        ids = set()
        for index in self.table.selectionModel().selectedRows() if self.table.selectionModel() else []:
            item = self.table.item(index.row(), COL_NAME)
            if item:
                ids.add(item.data(Qt.UserRole))
        return [job for job in self._jobs if job.id in ids]

    def _rebuild_table(self) -> None:
        self.table.setRowCount(0)
        self._rows.clear()
        self._bars.clear()
        for job in self._jobs:
            self._add_row(job)
            self._apply_job_state(
                job.id, job.stage.value, job.overall, job.message or job.error, job.display_name
            )

    def _change_folder_for_selection(self) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Nothing selected", "Select one or more rows first.")
            return
        start = str(jobs[0].destination)
        folder = QFileDialog.getExistingDirectory(self, "Destination folder for the selected videos", start)
        if not folder:
            return
        for job in jobs:
            if job.stage.is_final:
                continue
            job.destination = Path(folder)
            row = self._rows.get(job.id)
            if row is not None:
                item = self.table.item(row, COL_FOLDER)
                item.setText(folder)
                item.setToolTip(folder)
        self._log("info", f"{len(jobs)} video(s) will be saved in {folder}.")

    def _open_selected_folder(self) -> None:
        jobs = self._selected_jobs() or self._jobs
        if not jobs:
            open_in_file_manager(Path(self.destination_input.text().strip() or "."))
            return
        open_in_file_manager(Path(jobs[0].destination))

    def _remove_selected(self) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            return
        if self._worker and self._worker.isRunning():
            jobs = [job for job in jobs if job.stage in (Stage.QUEUED,) or job.stage.is_final]
        remove_ids = {job.id for job in jobs}
        self._jobs = [job for job in self._jobs if job.id not in remove_ids]
        self._rebuild_table()
        self._update_buttons()

    def _clear_finished(self) -> None:
        self._jobs = [job for job in self._jobs if not job.stage.is_final]
        self._rebuild_table()
        self._update_buttons()

    def _retry_failed(self) -> None:
        count = 0
        for job in self._jobs:
            if job.stage in (Stage.FAILED, Stage.CANCELLED):
                job.reset()
                count += 1
        if count:
            self._rebuild_table()
            self._log("info", f"{count} job(s) put back in the queue.")
        self._update_buttons()

    # --------------------------------------------------------------- run
    def _validated_destination(self) -> Optional[Path]:
        text = self.destination_input.text().strip()
        if not text:
            QMessageBox.warning(self, "Destination missing", "Choose a destination folder first.")
            return None
        path = Path(text).expanduser()
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Destination not usable", f"This folder cannot be used:\n{exc}")
            return None
        return path

    def _browse_destination(self) -> None:
        start = self.destination_input.text().strip() or str(default_output_dir())
        folder = QFileDialog.getExistingDirectory(self, "Default destination folder", start)
        if folder:
            self.destination_input.setText(folder)
            self.save_settings()

    def _start(self) -> None:
        if self._worker and self._worker.isRunning():
            return
        pending = [job for job in self._jobs if not job.stage.is_final]
        if not pending:
            QMessageBox.information(self, "Queue empty", "Add at least one link before starting.")
            return

        options = self._current_options()
        problem = options.validate()
        if problem:
            QMessageBox.warning(self, "Check the options", problem)
            return

        blocking = [d for d in missing_dependencies() if self._blocks(d.key, options)]
        if blocking:
            QMessageBox.warning(
                self,
                "Missing component",
                "These components are required for the selected outputs:\n\n"
                + "\n".join(f"- {d.label}: pip install -U {d.pip_name}" for d in blocking),
            )
            return

        self.save_settings()
        self.log_view.clear()
        self.overall_bar.setValue(0)
        self.overall_bar.setFormat("Working... %p%")

        self._worker = PipelineWorker(pending, options, self)
        self._worker.job_updated.connect(self._on_job_updated)
        self._worker.log_message.connect(self._log)
        self._worker.run_finished.connect(self._on_run_finished)
        self._worker.start()
        self._update_buttons()

    @staticmethod
    def _blocks(key: str, options: JobOptions) -> bool:
        if key == "yt_dlp":
            return True
        if key == "ffmpeg":
            # Video alone still works without FFmpeg: a single ready-made
            # stream is downloaded instead of merging two of them.
            return options.needs_audio_file
        if key == "faster_whisper":
            return options.transcribe
        return False

    def _stop(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._log("warning", "Stopping after the current step...")
            self.stop_button.setEnabled(False)

    def _on_job_updated(self, data: Dict) -> None:
        self._apply_job_state(
            data["id"],
            data["stage"],
            data["overall"],
            data.get("message") or data.get("error", ""),
            data.get("title") or data.get("url", ""),
        )
        for job in self._jobs:
            if job.id == data["id"]:
                job.title = data.get("title") or job.title
                job.destination = Path(data.get("destination") or job.destination)
                job.stage = Stage(data["stage"])
                job.overall = data["overall"]
                job.message = data.get("message", "")
                job.error = data.get("error", "")
                job.outputs = {key: Path(value) for key, value in (data.get("outputs") or {}).items()}
                break
        if self._jobs:
            self.overall_bar.setValue(int(sum(j.overall for j in self._jobs) / len(self._jobs)))

    def _apply_job_state(self, job_id: int, stage: str, overall: float, detail: str, name: str) -> None:
        row = self._rows.get(job_id)
        if row is None:
            return
        name_item = self.table.item(row, COL_NAME)
        if name_item and name:
            name_item.setText(name)
        step_item = self.table.item(row, COL_STEP)
        if step_item:
            step_item.setText(stage)
        detail_item = self.table.item(row, COL_DETAIL)
        if detail_item:
            detail_item.setText(detail or "")
            detail_item.setToolTip(detail or "")
        bar = self._bars.get(job_id)
        if bar:
            bar.setValue(int(overall))

    def _on_run_finished(self, summary: Dict) -> None:
        self.overall_bar.setFormat("Finished - %p%")
        self.overall_bar.setValue(100 if summary.get("failed", 0) == 0 else self.overall_bar.value())
        self.stop_button.setEnabled(True)
        self._worker = None
        self._update_buttons()
        QMessageBox.information(
            self,
            "Run finished",
            f"Completed: {summary.get('done', 0)}\n"
            f"Failed: {summary.get('failed', 0)}\n"
            f"Cancelled: {summary.get('cancelled', 0)}",
        )

    def _log(self, level: str, message: str) -> None:
        prefix = {"error": "[!]", "warning": "[*]", "debug": "   "}.get(level, "[.]")
        self.log_view.appendPlainText(f"{prefix} {message}")

    def _update_buttons(self) -> None:
        running = bool(self._worker and self._worker.isRunning())
        pending = any(not job.stage.is_final for job in self._jobs)
        self.start_button.setEnabled(not running and pending)
        self.start_button.setText("Working..." if running else "Start conversion")
        self.stop_button.setEnabled(running)

    # ------------------------------------------------------------- closing
    def shutdown(self) -> None:
        """Stop the worker and persist the settings."""
        self.save_settings()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(15000)

    def has_running_work(self) -> bool:
        return bool(self._worker and self._worker.isRunning())
