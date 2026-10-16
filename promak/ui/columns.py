"""The side-by-side arrangement shared by every tool screen.

Each tool shows three blocks: what to work on (links or files, folder,
options), the queue, and the activity log.  They sit next to each other
in three columns, so the queue and the log are always in view while the
options are being set.  The dividers between the columns can be dragged,
and the widths are remembered per tool.

On a small screen (a laptop, or a big zoom) the three columns may not fit
side by side.  Nothing is squeezed or cut then: the columns keep the width
they need and slide sideways inside a strip.  When the sliding stops, the
strip settles on the nearest column, like a magnet, so a column is never
left half in view; a row of buttons above (or Alt+1, Alt+2, Alt+3) jumps
straight to a column.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional, Sequence, Tuple

from PySide6.QtCore import QEasingCurve, QEvent, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
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
DEFAULT_WIDTHS = (470, 760, 340)
#: below this a column cannot be squeezed by dragging a divider
MINIMUM_WIDTHS = (380, 340, 220)
#: the names on the buttons that jump to a column on a small screen
COLUMN_NAMES = ("Settings", "Queue", "Activity")


class ColumnStrip(QWidget):
    """The columns of a tool screen, never hidden whatever the window size.

    When there is room the strip is invisible: the columns fill the width as
    before.  When there is not, the columns keep their own width and the
    strip slides sideways; once the sliding stops it settles on the nearest
    column (a "magnet"), and buttons above it jump to a column.
    """

    SNAP_DELAY_MS = 180      # how long after the last movement the magnet pulls
    SNAP_DURATION_MS = 240

    def __init__(self, splitter: QSplitter, names: Sequence[str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ColumnStrip")
        self.splitter = splitter
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # --- the buttons that jump to a column (shown only when needed)
        self.nav = QWidget()
        self.nav.setObjectName("ColumnNav")
        nav_row = QHBoxLayout(self.nav)
        nav_row.setContentsMargins(0, 0, 0, 0)
        nav_row.setSpacing(6)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: list = []
        for index in range(splitter.count()):
            name = names[index] if index < len(names) else f"Column {index + 1}"
            button = QPushButton(f"{index + 1}  {name}")
            button.setObjectName("ColumnNavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip(f"Show the {name.lower()} column  (Alt+{index + 1})")
            button.clicked.connect(lambda _checked=False, i=index: self.show_column(i))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            nav_row.addWidget(button)
        hint = QLabel("The window is narrow: slide sideways, or pick a column.")
        hint.setObjectName("HintLabel")
        nav_row.addWidget(hint, 1)
        layout.addWidget(self.nav)

        # --- the sliding strip itself
        self.scroll = QScrollArea()
        self.scroll.setObjectName("ColumnScroll")
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setWidget(splitter)
        layout.addWidget(self.scroll, 1)

        bar = self.scroll.horizontalScrollBar()
        self._animation = QPropertyAnimation(bar, b"value", self)
        self._animation.setDuration(self.SNAP_DURATION_MS)
        self._animation.setEasingCurve(QEasingCurve.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.SNAP_DELAY_MS)
        self._timer.timeout.connect(self.snap)
        bar.valueChanged.connect(self._on_moved)
        bar.sliderReleased.connect(self.snap)
        bar.rangeChanged.connect(lambda *_args: self._refresh())

        for index in range(min(9, splitter.count())):
            shortcut = QShortcut(QKeySequence(f"Alt+{index + 1}"), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda i=index: self.show_column(i))
        self._refresh()

    # ------------------------------------------------------------ helpers
    @property
    def bar(self):
        return self.scroll.horizontalScrollBar()

    def is_sliding(self) -> bool:
        """True when the columns do not all fit and the strip can move."""
        return self.bar.maximum() > 0

    def column_starts(self) -> list:
        """Where the strip stops: the left edge of each column, and the far end."""
        end = self.bar.maximum()
        stops = {min(end, max(0, self.splitter.widget(i).x())) for i in range(self.splitter.count())}
        stops.add(end)
        return sorted(stops)

    def current_column(self) -> int:
        """The column that takes most of the visible room."""
        left = self.bar.value()
        right = left + self.scroll.viewport().width()
        best, best_seen = 0, -1
        for index in range(self.splitter.count()):
            widget = self.splitter.widget(index)
            seen = min(right, widget.x() + widget.width()) - max(left, widget.x())
            if seen > best_seen:
                best, best_seen = index, seen
        return best

    # ------------------------------------------------------------- moving
    def show_column(self, index: int) -> None:
        """Slide so that column ``index`` is in view (from its left edge)."""
        if not 0 <= index < self.splitter.count():
            return
        widget = self.splitter.widget(index)
        self._glide_to(min(self.bar.maximum(), max(0, widget.x())))

    def snap(self) -> None:
        """Settle on the nearest column, if the strip stopped in between."""
        if not self.is_sliding() or self.bar.isSliderDown():
            return
        value = self.bar.value()
        target = min(self.column_starts(), key=lambda stop: abs(stop - value))
        if target != value:
            self._glide_to(target)

    def _glide_to(self, target: int) -> None:
        self._timer.stop()
        self._animation.stop()
        if target == self.bar.value():
            self._refresh()
            return
        self._animation.setStartValue(self.bar.value())
        self._animation.setEndValue(int(target))
        self._animation.start()

    def _on_moved(self, *_args) -> None:
        self._refresh_buttons()
        if self._animation.state() == QPropertyAnimation.Running or self.bar.isSliderDown():
            return
        self._timer.start()

    def _refresh(self) -> None:
        sliding = self.is_sliding()
        self.nav.setVisible(sliding)
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        if not self.nav_buttons:
            return
        button = self.nav_buttons[self.current_column()]
        if not button.isChecked():
            button.setChecked(True)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._timer.start()



def side_by_side(columns: Sequence[QWidget], settings_key: str,
                 names: Sequence[str] = COLUMN_NAMES) -> ColumnStrip:
    """Put ``columns`` next to each other and remember how wide they are.

    ``settings_key`` is where the widths are stored, for example
    ``"video.column_widths"``; ``names`` label the buttons that jump to a
    column when the window is too narrow to show them all.  The columns
    themselves are in the strip's ``splitter``.
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
    return ColumnStrip(splitter, names)


def folder_label(path) -> str:
    """How a destination folder is written in the queue: its name only.

    The whole path goes in the tooltip, so the column can stay narrow and
    leave the room to the name of the video or file.
    """
    text = str(path)
    name = Path(text).name
    return name or text


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
    # bigger letters (zoom) or a longer label later on: the column follows
    watcher = _FitWatcher(scroll, content)
    content.installEventFilter(watcher)
    scroll._fit_watcher = watcher          # kept alive with the column


class _FitWatcher(QObject):
    """Widens a left column again when what it holds needs more room."""

    def __init__(self, scroll: QScrollArea, content: QWidget) -> None:
        super().__init__(scroll)
        self.scroll = scroll
        self.content = content

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        if event.type() in (QEvent.LayoutRequest, QEvent.StyleChange, QEvent.FontChange):
            needed = (self.content.minimumSizeHint().width()
                      + self.scroll.verticalScrollBar().sizeHint().width() + 6)
            needed = max(MINIMUM_WIDTHS[0], needed)
            if needed != self.scroll.minimumWidth():
                self.scroll.setMinimumWidth(needed)
        return False


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
