"""The screen shared by every file-to-file tool.

It draws the three numbered boxes, the queue, the activity log and the
footer, and it runs the queue in a background thread.  A tool only has to
say which files it accepts, which options it offers and which engine does
the work - the rest is written once here.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QFrame,
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

from promak.core.batch import BatchEngine
from promak.core.config import get_config
from promak.core.filejobs import FileJob, FileStage, apply_snapshot
from promak.core.imaging import RASTER_EXTENSIONS, human_size
from promak.core.paths import default_output_dir, open_in_file_manager
from promak.ui.batch_worker import BatchWorker

log = logging.getLogger(__name__)


class FileQueuePanel(QWidget):
    """Base screen: add files, choose folders, set options, run the queue."""

    # ---- what a subclass describes -------------------------------------
    TOOL_ID = "tool"
    PAGE_TITLE = "Tool"
    PAGE_SUBTITLE = ""
    FILES_BOX_TITLE = "1 - Pictures"
    FILES_HINT = "Drag pictures into this window, or use the buttons."
    DESTINATION_BOX_TITLE = "2 - Destination folder"
    OPTIONS_BOX_TITLE = "3 - Options"
    FILE_DIALOG_FILTER = "Pictures (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp);;All files (*)"
    ACCEPTED_EXTENSIONS: Sequence[str] = RASTER_EXTENSIONS
    EXTRA_COLUMNS: Sequence[str] = ()
    START_LABEL = "Start"
    RUNNING_LABEL = "Working..."

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.config = get_config()
        self._jobs: List[FileJob] = []
        self._rows: Dict[int, int] = {}
        self._bars: Dict[int, QProgressBar] = {}
        self._worker: Optional[BatchWorker] = None

        self.setAcceptDrops(True)
        self._build_ui()
        self.load_settings()
        self._update_buttons()

    # ==================================================================
    # interface
    # ==================================================================
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(6)

        title = QLabel(self.PAGE_TITLE)
        title.setObjectName("PageTitle")
        outer.addWidget(title)
        if self.PAGE_SUBTITLE:
            subtitle = QLabel(self.PAGE_SUBTITLE)
            subtitle.setObjectName("PageSubtitle")
            subtitle.setWordWrap(True)
            outer.addWidget(subtitle)
        outer.addSpacing(8)

        self.notice = QLabel()
        self.notice.setObjectName("NoticeBanner")
        self.notice.setWordWrap(True)
        self.notice.setVisible(False)
        outer.addWidget(self.notice)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._build_setup_area())
        splitter.addWidget(self._build_queue_area())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([430, 450])
        outer.addWidget(splitter, 1)
        outer.addLayout(self._build_footer())

    def _build_setup_area(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        # --- 1. files ---------------------------------------------------
        files_box = QGroupBox(self.FILES_BOX_TITLE)
        files_layout = QVBoxLayout(files_box)
        self.drop_hint = QLabel(self.FILES_HINT)
        self.drop_hint.setObjectName("DropArea")
        self.drop_hint.setAlignment(Qt.AlignCenter)
        self.drop_hint.setMinimumHeight(74)
        self.drop_hint.setWordWrap(True)
        files_layout.addWidget(self.drop_hint)

        buttons = QHBoxLayout()
        self.count_label = QLabel("No file in the queue.")
        self.count_label.setObjectName("HintLabel")
        add_files = QPushButton("Add files...")
        add_files.clicked.connect(self._browse_files)
        add_folder = QPushButton("Add a folder...")
        add_folder.setToolTip("Add every supported picture directly inside a folder.")
        add_folder.clicked.connect(self._browse_folder)
        buttons.addWidget(self.count_label, 1)
        buttons.addWidget(add_files)
        buttons.addWidget(add_folder)
        files_layout.addLayout(buttons)
        layout.addWidget(files_box)

        # --- 2. destination ---------------------------------------------
        dest_box = QGroupBox(self.DESTINATION_BOX_TITLE)
        dest_layout = QVBoxLayout(dest_box)
        row = QHBoxLayout()
        self.destination_input = QLineEdit()
        self.destination_input.setPlaceholderText("Folder where the new files will be saved")
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse_destination)
        row.addWidget(self.destination_input, 1)
        row.addWidget(browse)
        dest_layout.addLayout(row)

        self.beside_check = QCheckBox("Save each new file next to its original")
        self.beside_check.setToolTip(
            "The new file is written in the same folder as the picture it came from.\n"
            "The original is never replaced: the new file gets its own name."
        )
        self.beside_check.toggled.connect(self._on_beside_toggled)
        dest_layout.addWidget(self.beside_check)

        hint = QLabel(
            "This folder is used for every file you add next. To send some files "
            'somewhere else, select their rows in the queue and use "Change folder" '
            "- general, specific or mixed all work. Your original files are never "
            "changed or deleted."
        )
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        dest_layout.addWidget(hint)
        layout.addWidget(dest_box)

        # --- 3. options (the subclass fills this one) -------------------
        options_box = QGroupBox(self.OPTIONS_BOX_TITLE)
        self.build_options(options_box)
        layout.addWidget(options_box)

        extra = self.build_extra_area()
        if extra is not None:
            layout.addWidget(extra)

        layout.addStretch(1)
        scroll.setWidget(container)
        return scroll

    def _build_queue_area(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 6, 0, 0)
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

        self._columns = ["File", *self.EXTRA_COLUMNS, "Destination", "Step", "Progress", "Details"]
        self.COL_NAME = 0
        self.COL_DESTINATION = 1 + len(self.EXTRA_COLUMNS)
        self.COL_STEP = self.COL_DESTINATION + 1
        self.COL_PROGRESS = self.COL_STEP + 1
        self.COL_DETAIL = self.COL_PROGRESS + 1

        self.table = QTableWidget(0, len(self._columns))
        self.table.setHorizontalHeaderLabels(self._columns)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        view = self.table.horizontalHeader()
        view.setSectionResizeMode(self.COL_NAME, QHeaderView.Stretch)
        for column in range(1, len(self._columns)):
            view.setSectionResizeMode(column, QHeaderView.Interactive)
        for index in range(len(self.EXTRA_COLUMNS)):
            self.table.setColumnWidth(1 + index, 96)
        self.table.setColumnWidth(self.COL_DESTINATION, 190)
        self.table.setColumnWidth(self.COL_STEP, 84)
        self.table.setColumnWidth(self.COL_PROGRESS, 110)
        self.table.setColumnWidth(self.COL_DETAIL, 230)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.table, 1)

        log_label = QLabel("Activity")
        log_label.setObjectName("SectionLabel")
        layout.addWidget(log_label)
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setFixedHeight(110)
        layout.addWidget(self.log_view)
        return container

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setFormat("Idle")
        footer.addWidget(self.overall_bar, 1)

        self.start_button = QPushButton(self.START_LABEL)
        self.start_button.setObjectName("PrimaryButton")
        self.start_button.setMinimumWidth(170)
        self.start_button.clicked.connect(self._start)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.clicked.connect(self._stop)
        footer.addWidget(self.start_button)
        footer.addWidget(self.stop_button)
        return footer

    # ==================================================================
    # hooks for the subclasses
    # ==================================================================
    def build_options(self, box: QGroupBox) -> None:
        """Fill the third box with the tool's own controls."""
        QVBoxLayout(box).addWidget(QLabel("No option."))

    def build_extra_area(self) -> Optional[QWidget]:
        """An optional fourth block, for example a preview."""
        return None

    def create_engine(self, cancel_event: threading.Event) -> BatchEngine:
        raise NotImplementedError

    def extra_values(self, job: FileJob) -> Sequence[str]:
        return ()

    def load_settings(self) -> None:
        destination = self.config.get(f"{self.TOOL_ID}.destination") or str(default_output_dir())
        self.destination_input.setText(destination)
        self.beside_check.setChecked(bool(self.config.get(f"{self.TOOL_ID}.beside_original", False)))
        self._on_beside_toggled(self.beside_check.isChecked())

    def save_settings(self) -> None:
        self.config.update(
            {
                f"{self.TOOL_ID}.destination": self.destination_input.text().strip(),
                f"{self.TOOL_ID}.beside_original": self.beside_check.isChecked(),
            }
        )

    def validate_before_start(self) -> Optional[str]:
        """Return a message when the run must not start."""
        return None

    def on_job_selected(self, job: Optional[FileJob]) -> None:
        """Called when the selected row changes (used for the preview)."""

    def on_job_finished(self, job: FileJob) -> None:
        """Called when one file is done (used to refresh the preview)."""

    # ==================================================================
    # adding files
    # ==================================================================
    def accepts(self, path: Path) -> bool:
        return Path(path).suffix.lower() in tuple(self.ACCEPTED_EXTENSIONS)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        paths: List[Path] = []
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if not local:
                continue
            path = Path(local)
            if path.is_dir():
                paths.extend(self._scan_folder(path))
            else:
                paths.append(path)
        self.add_files(paths)
        event.acceptProposedAction()

    def _scan_folder(self, folder: Path) -> List[Path]:
        try:
            entries = sorted(p for p in folder.iterdir() if p.is_file())
        except OSError as exc:
            self._log("error", f"The folder cannot be read: {exc}")
            return []
        return [p for p in entries if self.accepts(p)]

    def _browse_files(self) -> None:
        start = self.destination_input.text().strip() or str(Path.home())
        files, _ = QFileDialog.getOpenFileNames(self, "Choose pictures", start, self.FILE_DIALOG_FILTER)
        self.add_files([Path(f) for f in files])

    def _browse_folder(self) -> None:
        start = self.destination_input.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder of pictures", start)
        if not folder:
            return
        found = self._scan_folder(Path(folder))
        if not found:
            QMessageBox.information(
                self, "Nothing to add", "That folder holds no picture this tool can open."
            )
            return
        self.add_files(found)

    def add_files(self, paths: Sequence[Path]) -> None:
        if not paths:
            return
        destination = self._validated_destination()
        if destination is None:
            return

        known = {str(job.source).lower() for job in self._jobs}
        added = 0
        rejected = 0
        for path in paths:
            path = Path(path)
            if not path.is_file():
                continue
            if not self.accepts(path):
                rejected += 1
                continue
            if str(path).lower() in known:
                continue
            folder = path.parent if self.beside_check.isChecked() else destination
            job = FileJob(source=path, destination=folder)
            self._jobs.append(job)
            known.add(str(path).lower())
            self._add_row(job)
            added += 1

        if added:
            self._log("info", f"Added {added} file(s) to the queue.")
        if rejected:
            self._log(
                "warning",
                f"{rejected} file(s) were ignored: this tool only opens "
                + ", ".join(e.lstrip('.').upper() for e in self.ACCEPTED_EXTENSIONS)
                + ".",
            )
        self._refresh_count()
        self._update_buttons()

    # ==================================================================
    # the table
    # ==================================================================
    def _add_row(self, job: FileJob) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self._rows[job.id] = row

        name_item = QTableWidgetItem(job.display_name)
        name_item.setToolTip(str(job.source))
        name_item.setData(Qt.UserRole, job.id)
        self.table.setItem(row, self.COL_NAME, name_item)

        for index in range(len(self.EXTRA_COLUMNS)):
            self.table.setItem(row, 1 + index, QTableWidgetItem(""))

        folder_item = QTableWidgetItem(str(job.destination))
        folder_item.setToolTip(str(job.destination))
        self.table.setItem(row, self.COL_DESTINATION, folder_item)
        self.table.setItem(row, self.COL_STEP, QTableWidgetItem(job.stage.value))

        bar = QProgressBar()
        bar.setRange(0, 100)
        bar.setValue(0)
        bar.setTextVisible(True)
        bar.setFormat("%p%")
        self.table.setCellWidget(row, self.COL_PROGRESS, bar)
        self._bars[job.id] = bar

        self.table.setItem(row, self.COL_DETAIL, QTableWidgetItem(""))
        self._refresh_row(job)

    def _refresh_row(self, job: FileJob) -> None:
        row = self._rows.get(job.id)
        if row is None:
            return
        for index, value in enumerate(self.extra_values(job)):
            item = self.table.item(row, 1 + index)
            if item is not None:
                item.setText(str(value))
        folder_item = self.table.item(row, self.COL_DESTINATION)
        if folder_item is not None:
            folder_item.setText(str(job.destination))
            folder_item.setToolTip(str(job.destination))
        step_item = self.table.item(row, self.COL_STEP)
        if step_item is not None:
            step_item.setText(job.stage.value)
        detail_item = self.table.item(row, self.COL_DETAIL)
        if detail_item is not None:
            detail_item.setText(job.detail)
            detail_item.setToolTip(job.detail)
        bar = self._bars.get(job.id)
        if bar is not None:
            bar.setValue(int(job.progress))

    def _rebuild_table(self) -> None:
        self.table.setRowCount(0)
        self._rows.clear()
        self._bars.clear()
        for job in self._jobs:
            self._add_row(job)
        self._refresh_count()

    def _refresh_count(self) -> None:
        total = len(self._jobs)
        if not total:
            self.count_label.setText("No file in the queue.")
            return
        weight = sum(job.source_bytes for job in self._jobs)
        self.count_label.setText(f"{total} file(s) in the queue - {human_size(weight)} in total.")

    def _selected_jobs(self) -> List[FileJob]:
        model = self.table.selectionModel()
        if model is None:
            return []
        ids = set()
        for index in model.selectedRows():
            item = self.table.item(index.row(), self.COL_NAME)
            if item is not None:
                ids.add(item.data(Qt.UserRole))
        return [job for job in self._jobs if job.id in ids]

    def _on_selection_changed(self) -> None:
        selected = self._selected_jobs()
        self.on_job_selected(selected[0] if selected else None)
        self._update_buttons()

    def _change_folder_for_selection(self) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Nothing selected", "Select one or more rows first.")
            return
        folder = QFileDialog.getExistingDirectory(
            self, "Destination folder for the selected files", str(jobs[0].destination)
        )
        if not folder:
            return
        for job in jobs:
            if job.stage.is_final:
                continue
            job.destination = Path(folder)
            self._refresh_row(job)
        self._log("info", f"{len(jobs)} file(s) will be saved in {folder}.")

    def _open_selected_folder(self) -> None:
        jobs = self._selected_jobs() or self._jobs
        target = Path(jobs[0].destination) if jobs else Path(self.destination_input.text().strip() or ".")
        open_in_file_manager(target)

    def _remove_selected(self) -> None:
        jobs = self._selected_jobs()
        if not jobs:
            return
        if self._worker and self._worker.isRunning():
            jobs = [job for job in jobs if job.stage is FileStage.QUEUED or job.stage.is_final]
        remove = {job.id for job in jobs}
        self._jobs = [job for job in self._jobs if job.id not in remove]
        self._rebuild_table()
        self._update_buttons()

    def _clear_finished(self) -> None:
        self._jobs = [job for job in self._jobs if not job.stage.is_final]
        self._rebuild_table()
        self._update_buttons()

    def _retry_failed(self) -> None:
        count = 0
        for job in self._jobs:
            if job.stage in (FileStage.FAILED, FileStage.CANCELLED):
                job.reset()
                count += 1
        if count:
            self._rebuild_table()
            self._log("info", f"{count} file(s) put back in the queue.")
        self._update_buttons()

    # ==================================================================
    # running
    # ==================================================================
    def _on_beside_toggled(self, checked: bool) -> None:
        self.destination_input.setEnabled(not checked)
        if checked:
            for job in self._jobs:
                if not job.stage.is_final:
                    job.destination = job.source.parent
                    self._refresh_row(job)

    def _validated_destination(self) -> Optional[Path]:
        if self.beside_check.isChecked():
            return Path(self.destination_input.text().strip() or str(default_output_dir()))
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
            QMessageBox.information(self, "Queue empty", "Add at least one file before starting.")
            return
        problem = self.validate_before_start()
        if problem:
            QMessageBox.warning(self, "Check the options", problem)
            return
        if self._validated_destination() is None:
            return

        self.save_settings()
        self.log_view.clear()
        self.overall_bar.setValue(0)
        self.overall_bar.setFormat("Working... %p%")

        self._worker = BatchWorker(pending, self.create_engine, self)
        self._worker.job_updated.connect(self._on_job_updated)
        self._worker.log_message.connect(self._log)
        self._worker.run_finished.connect(self._on_run_finished)
        self._worker.start()
        self._update_buttons()

    def _stop(self) -> None:
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._log("warning", "Stopping after the current file...")
            self.stop_button.setEnabled(False)

    def _on_job_updated(self, data: Dict) -> None:
        for job in self._jobs:
            if job.id != data["id"]:
                continue
            was_final = job.stage.is_final
            apply_snapshot(job, data)
            self._refresh_row(job)
            if job.stage.is_final and not was_final:
                self.on_job_finished(job)
            break
        if self._jobs:
            total = sum(100.0 if j.stage.is_final else j.progress for j in self._jobs)
            self.overall_bar.setValue(int(total / len(self._jobs)))

    def _on_run_finished(self, summary: Dict) -> None:
        self.overall_bar.setFormat("Finished - %p%")
        if not summary.get("failed") and not summary.get("cancelled"):
            self.overall_bar.setValue(100)
        self.stop_button.setEnabled(True)
        self._worker = None
        self._update_buttons()
        self._refresh_count()
        QMessageBox.information(
            self,
            "Run finished",
            f"Completed: {summary.get('done', 0)}\n"
            f"Left as they were: {summary.get('skipped', 0)}\n"
            f"Failed: {summary.get('failed', 0)}\n"
            f"Cancelled: {summary.get('cancelled', 0)}",
        )

    def _log(self, level: str, message: str) -> None:
        prefix = {"error": "[!]", "warning": "[*]", "debug": "   "}.get(level, "[.]")
        self.log_view.appendPlainText(f"{prefix} {message}")

    def show_notice(self, message: str, kind: str = "info") -> None:
        """A coloured strip under the title, for warnings worth reading."""
        self.notice.setProperty("kind", kind)
        self.notice.setText(message)
        self.notice.setVisible(bool(message))
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)

    def _update_buttons(self) -> None:
        running = bool(self._worker and self._worker.isRunning())
        pending = any(not job.stage.is_final for job in self._jobs)
        self.start_button.setEnabled(not running and pending)
        self.start_button.setText(self.RUNNING_LABEL if running else self.START_LABEL)
        self.stop_button.setEnabled(running)

    # ------------------------------------------------------------- closing
    def shutdown(self) -> None:
        self.save_settings()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(15000)

    def has_running_work(self) -> bool:
        return bool(self._worker and self._worker.isRunning())
