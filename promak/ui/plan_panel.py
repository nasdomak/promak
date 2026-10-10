"""The screen shared by the "look first, then act" tools.

Finding duplicates, sorting photos by date, comparing two folders or
deleting files for good all work the same way:

1. the user says where to look and how (left column);
2. **Look** - the work is planned in a background thread and every change
   is shown in the middle column before anything is touched;
3. **the action button** - only after a confirmation, again in the
   background, with a progress bar and a Stop button;
4. where it makes sense, **Undo**.

A tool only fills the left column, the middle column and the two jobs.
Everything that is the same - the three columns, the footer, the worker
thread, the progress, the log - is written once here.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Optional, Sequence, Tuple

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from promak.core.batch import BatchCancelled
from promak.core.config import get_config
from promak.core.eta import RemainingTime
from promak.ui.columns import activity_column, fit_setup_column, queue_buttons, side_by_side

log = logging.getLogger(__name__)

#: what a background job receives: progress(share 0..1, text), log(level, text), cancel event
TaskFunction = Callable[[Callable[[float, str], None], Callable[[str, str], None], threading.Event], Any]


class TaskWorker(QThread):
    """Runs one function in the background and hands its result back."""

    progress = Signal(float, str)
    log_message = Signal(str, str)
    done = Signal(object, str, bool)      # result, error message, cancelled

    def __init__(self, function: TaskFunction, parent=None) -> None:
        super().__init__(parent)
        self._function = function
        self.cancel_event = threading.Event()

    def cancel(self) -> None:
        self.cancel_event.set()

    def run(self) -> None:  # noqa: D102 - QThread entry point
        try:
            result = self._function(
                lambda share, text="": self.progress.emit(float(share), text),
                lambda level, text: self.log_message.emit(level, text),
                self.cancel_event,
            )
        except BatchCancelled:
            self.done.emit(None, "", True)
            return
        except Exception as exc:  # shown to the user, never a crash
            log.debug("Background job failed", exc_info=True)
            self.done.emit(None, str(exc) or exc.__class__.__name__, False)
            return
        self.done.emit(result, "", self.cancel_event.is_set())


class PlanPanel(QWidget):
    """Base screen: set up, look, check the preview, act."""

    TOOL_ID = "plan"
    PAGE_TITLE = "Tool"
    PAGE_SUBTITLE = ""
    PREVIEW_TITLE = "Preview"
    SCAN_LABEL = "Look"
    APPLY_LABEL = "Do it"
    APPLY_DANGER = False             # a red button for tools that delete
    UNDO_LABEL = ""                  # "" = no undo button
    #: keys of :data:`promak.core.dependencies.TOOL_COMPONENTS` the tool needs
    COMPONENTS: Sequence[str] = ()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.config = get_config()
        self._worker: Optional[TaskWorker] = None
        self._eta = RemainingTime()
        self.setAcceptDrops(True)
        self._build_ui()
        self.load_settings()
        self.refresh_buttons()
        message = self.missing_components_message()
        if message:
            self.show_notice(message, "warning")

    # ================================================================ UI
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

        activity, self.log_view = activity_column(self.build_extra_area())
        outer.addWidget(
            side_by_side([self._build_setup(), self._build_middle(), activity], f"{self.TOOL_ID}.column_widths"),
            1,
        )
        outer.addLayout(self._build_footer())

    def _build_setup(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)
        self.build_setup(layout)
        layout.addStretch(1)
        scroll.setWidget(container)
        fit_setup_column(scroll, container)
        return scroll

    def _build_middle(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 6, 0, 0)
        layout.setSpacing(8)
        label = QLabel(self.PREVIEW_TITLE)
        label.setObjectName("SectionLabel")
        layout.addWidget(label)
        actions = self.preview_buttons()
        if actions:
            layout.addLayout(queue_buttons(actions))
        layout.addWidget(self.build_preview(), 1)
        return container

    def _build_footer(self) -> QHBoxLayout:
        footer = QHBoxLayout()
        footer.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("Idle")
        footer.addWidget(self.progress_bar, 1)
        self.summary_label = QLabel("")
        self.summary_label.setObjectName("HintLabel")
        self.summary_label.setWordWrap(True)
        self.summary_label.setMinimumWidth(260)
        self.summary_label.setMaximumWidth(460)
        footer.addWidget(self.summary_label)
        self.undo_button = QPushButton(self.UNDO_LABEL or "Undo")
        self.undo_button.clicked.connect(self._undo_clicked)
        self.undo_button.setVisible(bool(self.UNDO_LABEL))
        footer.addWidget(self.undo_button)
        self.scan_button = QPushButton(self.SCAN_LABEL)
        self.scan_button.setMinimumWidth(120)
        self.scan_button.clicked.connect(self.scan)
        footer.addWidget(self.scan_button)
        self.apply_button = QPushButton(self.APPLY_LABEL)
        self.apply_button.setObjectName("DangerButton" if self.APPLY_DANGER else "PrimaryButton")
        self.apply_button.setMinimumWidth(170)
        self.apply_button.clicked.connect(self.apply)
        footer.addWidget(self.apply_button)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("DangerButton")
        self.stop_button.clicked.connect(self.stop)
        footer.addWidget(self.stop_button)
        return footer

    # ========================================================= the hooks
    def build_setup(self, layout: QVBoxLayout) -> None:
        """Fill the left column (numbered boxes)."""

    def build_preview(self) -> QWidget:
        """The middle column; by default an empty read-only table."""
        self.table = make_table(("Item",))
        return self.table

    def preview_buttons(self) -> Sequence[Tuple[str, Callable]]:
        return ()

    def build_extra_area(self) -> Optional[QWidget]:
        """An optional block above the activity log."""
        return None

    def load_settings(self) -> None:
        pass

    def save_settings(self) -> None:
        pass

    def validate_scan(self) -> Optional[str]:
        return None

    def scan_task(self) -> TaskFunction:
        raise NotImplementedError

    def on_scanned(self, result: Any) -> None:
        pass

    def can_apply(self) -> bool:
        return False

    def confirm_apply(self) -> bool:
        """Ask before acting; True to go on."""
        return True

    def apply_task(self) -> TaskFunction:
        raise NotImplementedError

    def on_applied(self, result: Any) -> None:
        pass

    def can_undo(self) -> bool:
        return False

    def undo(self) -> None:
        pass

    def on_dropped(self, paths) -> None:
        """Files or folders dragged onto the screen."""

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        from pathlib import Path

        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.toLocalFile()]
        if paths:
            self.on_dropped(paths)
        event.acceptProposedAction()

    # ======================================================== components
    def missing_components_message(self) -> str:
        if not self.COMPONENTS:
            return ""
        from promak.core.dependencies import missing_message, missing_tool_dependencies

        return missing_message(missing_tool_dependencies(list(self.COMPONENTS)))

    # ========================================================== running
    def scan(self) -> None:
        if self.is_busy():
            return
        problem = self.missing_components_message() or self.validate_scan()
        if problem:
            QMessageBox.warning(self, "Check the options", problem)
            return
        self.save_settings()
        self.log_view.clear()
        self.run_task(self.scan_task(), self._scanned, "Looking...")

    def _scanned(self, result: Any) -> None:
        self.on_scanned(result)

    def apply(self) -> None:
        if self.is_busy() or not self.can_apply():
            return
        if not self.confirm_apply():
            return
        self.save_settings()
        self.run_task(self.apply_task(), self.on_applied, "Working...")

    def _undo_clicked(self) -> None:
        if not self.is_busy() and self.can_undo():
            self.undo()
            self.refresh_buttons()

    def run_task(self, function: TaskFunction, on_done: Callable[[Any], None], busy_text: str) -> None:
        """Run ``function`` in the background; ``on_done(result)`` when it ends well."""
        self._busy_text = busy_text
        self._on_done = on_done
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"{busy_text} - estimating time left")
        self._eta.start()
        self._worker = TaskWorker(function, self)
        self._worker.progress.connect(self._on_progress)
        self._worker.log_message.connect(self.log)
        self._worker.done.connect(self._on_task_done)
        self._worker.start()
        self.refresh_buttons()

    def run_now(self, function: TaskFunction) -> Any:
        """Run a job in this thread (tests, tiny jobs); errors are raised."""
        return function(lambda *_a: None, self.log, threading.Event())

    def _on_progress(self, share: float, text: str) -> None:
        share = max(0.0, min(1.0, share))
        self.progress_bar.setValue(int(share * 1000))
        detail = f" - {text}" if text else ""
        self.progress_bar.setFormat(f"{self._busy_text} {share * 100:.0f}%{detail} - {self._eta.describe(share)}")

    def _on_task_done(self, result: Any, error: str, cancelled: bool) -> None:
        elapsed = int(self._eta.elapsed())
        self._eta.stop()
        self._worker = None
        if error:
            self.progress_bar.setFormat("Stopped by a problem")
            self.log("error", error)
            QMessageBox.warning(self, self.PAGE_TITLE, error)
        elif cancelled:
            self.progress_bar.setFormat("Stopped")
            self.log("warning", "Stopped.")
            if result is not None:
                self._on_done(result)
        else:
            self.progress_bar.setValue(1000)
            self.progress_bar.setFormat(f"Finished in {elapsed // 60}m {elapsed % 60:02d}s")
            self._on_done(result)
        self.refresh_buttons()

    def stop(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self.log("warning", "Stopping...")

    def is_busy(self) -> bool:
        return bool(self._worker and self._worker.isRunning())

    def refresh_buttons(self) -> None:
        busy = self.is_busy()
        self.scan_button.setEnabled(not busy)
        self.apply_button.setEnabled(not busy and self.can_apply())
        self.stop_button.setEnabled(busy)
        self.undo_button.setEnabled(not busy and self.can_undo())

    # ============================================================ helpers
    def log(self, level: str, message: str) -> None:
        prefix = {"error": "[!]", "warning": "[*]", "debug": "   "}.get(level, "[.]")
        self.log_view.appendPlainText(f"{prefix} {message}")

    _log = log

    def show_notice(self, message: str, kind: str = "info") -> None:
        self.notice.setProperty("kind", kind)
        self.notice.setText(message)
        self.notice.setVisible(bool(message))
        self.notice.style().unpolish(self.notice)
        self.notice.style().polish(self.notice)

    def ask(self, title: str, text: str, default_yes: bool = True) -> bool:
        answer = QMessageBox.question(self, title, text, QMessageBox.Yes | QMessageBox.No,
                                      QMessageBox.Yes if default_yes else QMessageBox.No)
        return answer == QMessageBox.Yes

    # ----------------------------------------------------------- closing
    def shutdown(self) -> None:
        self.save_settings()
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(15000)

    def has_running_work(self) -> bool:
        return self.is_busy()


def make_table(columns: Sequence[str], stretch: Sequence[int] = (0,)) -> QTableWidget:
    """A read-only table with whole-row selection, as every preview uses."""
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    for column in range(len(columns)):
        header.setSectionResizeMode(column, QHeaderView.Stretch if column in stretch else QHeaderView.Interactive)
        if column not in stretch:
            table.setColumnWidth(column, 110)
    return table


# ------------------------------------------------------------ small parts
class FolderList(QWidget):
    """A short list of folders with Add / Remove, for tools that look in several."""

    def __init__(self, hint: str = "Drag folders here, or use Add folder.", parent=None) -> None:
        from PySide6.QtWidgets import QListWidget

        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.list = QListWidget()
        self.list.setObjectName("PlainList")
        self.list.setMinimumHeight(86)
        self.list.setMaximumHeight(130)
        self.list.setToolTip(hint)
        layout.addWidget(self.list)
        row = QHBoxLayout()
        add = QPushButton("Add folder...")
        add.clicked.connect(self._browse)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        row.addWidget(add, 1)
        row.addWidget(remove, 1)
        layout.addLayout(row)
        self.hint = QLabel(hint)
        self.hint.setObjectName("HintLabel")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)

    def folders(self):
        from pathlib import Path

        return [Path(self.list.item(i).text()) for i in range(self.list.count())]

    def add(self, folder) -> None:
        text = str(folder)
        if text and text not in [self.list.item(i).text() for i in range(self.list.count())]:
            self.list.addItem(text)

    def set_folders(self, folders) -> None:
        self.list.clear()
        for folder in folders:
            self.add(folder)

    def _browse(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        start = self.list.item(self.list.count() - 1).text() if self.list.count() else str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose a folder", start)
        if folder:
            self.add(folder)

    def _remove(self) -> None:
        for item in self.list.selectedItems() or ([self.list.item(self.list.count() - 1)] if self.list.count() else []):
            self.list.takeItem(self.list.row(item))


def folder_field(placeholder: str, dialog_title: str = "Choose a folder"):
    """A line to type a folder in, with a Browse button: ``(widget, line edit)``."""
    from pathlib import Path

    from PySide6.QtWidgets import QFileDialog, QLineEdit

    holder = QWidget()
    row = QHBoxLayout(holder)
    row.setContentsMargins(0, 0, 0, 0)
    line = QLineEdit()
    line.setPlaceholderText(placeholder)
    browse = QPushButton("Browse...")

    def pick() -> None:
        folder = QFileDialog.getExistingDirectory(holder, dialog_title, line.text().strip() or str(Path.home()))
        if folder:
            line.setText(folder)

    browse.clicked.connect(pick)
    row.addWidget(line, 1)
    row.addWidget(browse)
    return holder, line


def combo(items) -> QComboBox:
    """A drop-down list of ``(label, value)`` pairs."""
    box = QComboBox()
    for label, value in items:
        box.addItem(label, value)
    return box


def select(box, value) -> None:
    """Choose the entry whose value is ``value`` (the first one if none)."""
    index = box.findData(value)
    box.setCurrentIndex(index if index >= 0 else 0)
