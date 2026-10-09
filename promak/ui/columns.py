"""The side-by-side arrangement shared by every tool screen.

Each tool shows three blocks: what to work on (links or files, folder,
options), the queue, and the activity log.  They sit next to each other
in three columns, so the queue and the log are always in view while the
options are being set.  The dividers between the columns can be dragged,
and the widths are remembered per tool.
"""

from __future__ import annotations

from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from promak.core.config import get_config

#: starting widths of the three columns (setup, queue, activity), in pixels;
#: Qt scales them to the room actually available
DEFAULT_WIDTHS = (500, 640, 360)
#: below this a column cannot be squeezed by dragging a divider
MINIMUM_WIDTHS = (380, 340, 220)


def side_by_side(columns: Sequence[QWidget], settings_key: str) -> QSplitter:
    """Put ``columns`` next to each other and remember how wide they are.

    ``settings_key`` is where the widths are stored, for example
    ``"video.column_widths"``.
    """
    config = get_config()
    splitter = QSplitter(Qt.Horizontal)
    splitter.setObjectName("ColumnSplitter")
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(14)
    for index, widget in enumerate(columns):
        if index < len(MINIMUM_WIDTHS):
            # a column may already know it needs more (see fit_setup_column)
            widget.setMinimumWidth(max(widget.minimumWidth(), MINIMUM_WIDTHS[index]))
        splitter.addWidget(widget)
        # the queue takes the extra room when the window grows
        splitter.setStretchFactor(index, 1 if index == 1 else 0)

    saved = config.get(settings_key)
    widths = list(DEFAULT_WIDTHS[: len(columns)])
    if isinstance(saved, list) and len(saved) == len(columns):
        try:
            candidate = [int(value) for value in saved]
        except (TypeError, ValueError):
            candidate = []
        if candidate and all(value > 0 for value in candidate):
            widths = candidate
    splitter.setSizes(widths)

    splitter.splitterMoved.connect(
        lambda *_args: config.set(settings_key, [int(v) for v in splitter.sizes()])
    )
    return splitter


def fit_setup_column(scroll: QScrollArea, content: QWidget) -> None:
    """Make the left column follow its own width, never cut its content.

    The column scrolls up and down only.  Drop-down lists stop asking for
    the width of their longest entry (the open list still shows it whole),
    and the column is never squeezed below what its content needs.
    """
    for combo in content.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(8)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    needed = content.minimumSizeHint().width() + scroll.verticalScrollBar().sizeHint().width() + 6
    scroll.setMinimumWidth(max(scroll.minimumWidth(), needed))


def queue_buttons(actions: Sequence[Tuple[str, Callable]], per_row: int = 3) -> QGridLayout:
    """The queue's buttons on two short rows, so they fit a narrow column."""
    grid = QGridLayout()
    grid.setHorizontalSpacing(8)
    grid.setVerticalSpacing(8)
    for index, (text, slot) in enumerate(actions):
        button = QPushButton(text)
        button.clicked.connect(slot)
        grid.addWidget(button, index // per_row, index % per_row)
    return grid


def activity_column(extra: Optional[QWidget] = None) -> Tuple[QWidget, QPlainTextEdit]:
    """The third column: the activity log, as tall as the window allows.

    ``extra`` (for example the before/after preview of the picture tools)
    goes on top of the log, so it is next to the queue it belongs to.
    """
    container = QWidget()
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    if extra is not None:
        layout.addWidget(extra)
    label = QLabel("Activity")
    label.setObjectName("SectionLabel")
    layout.addWidget(label)
    log_view = QPlainTextEdit()
    log_view.setObjectName("LogView")
    log_view.setReadOnly(True)
    log_view.setMaximumBlockCount(2000)
    log_view.setLineWrapMode(QPlainTextEdit.WidgetWidth)
    layout.addWidget(log_view, 1)
    return container, log_view
