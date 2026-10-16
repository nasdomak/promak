"""The application shell: sidebar of tools plus the active tool page."""

from __future__ import annotations

import logging
from typing import Dict, List

from PySide6.QtCore import QByteArray, QEvent, QSize, Qt
from PySide6.QtGui import QGuiApplication, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

import promak
from promak.core.config import get_config
from promak.core.paths import asset_file
from promak.core.tool_registry import registry
from promak.ui.theme import normalise as normalise_theme
from promak.ui.theme import normalise_zoom, other_theme, palette, stylesheet, zoom_step
from promak.ui.theme_icons import switch_icon

log = logging.getLogger(__name__)

#: the smallest window: below this even one column would be cramped
MINIMUM_WINDOW = (760, 500)
#: the size of a first start, when the screen has room for it
FIRST_WINDOW = (1440, 880)
#: the sidebar's width at the normal zoom
SIDEBAR_WIDTH = 232

#: where a sidebar row keeps its group name (headings only) and its search words
HEADING_ROLE = Qt.UserRole + 1
SEARCH_ROLE = Qt.UserRole + 2


class MainWindow(QMainWindow):
    """Hosts every Promak tool behind one window."""

    def __init__(self) -> None:
        super().__init__()
        self.config = get_config()
        self._pages: Dict[str, int] = {}
        self._theme = normalise_theme(self.config.get("app.theme"))
        self._zoom = normalise_zoom(self.config.get("app.zoom", 1.0))

        self.setWindowTitle(f"Promak {promak.__version__}")
        # small on purpose: on a laptop the columns slide instead of hiding
        self.setMinimumSize(*MINIMUM_WINDOW)
        self.resize(*self._fitting_size(*FIRST_WINDOW))

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self._populate_tools()
        self._build_zoom_controls()
        self._restore_geometry()
        self.statusBar().showMessage("Ready")

    # ----------------------------------------------------------- sidebar
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(round(SIDEBAR_WIDTH * self._zoom))
        self.sidebar = sidebar
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(0)

        brand = QWidget()
        brand.setObjectName("SidebarBrand")
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(18, 20, 16, 2)
        brand_row.setSpacing(10)
        logo = QLabel()
        logo.setFixedSize(QSize(30, 30))
        badge = asset_file("promak-32.png") or asset_file("promak.png")
        if badge is not None:
            logo.setPixmap(
                QPixmap(str(badge)).scaled(30, 30, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        title = QLabel("Promak")
        title.setObjectName("SidebarTitle")
        brand_row.addWidget(logo)
        brand_row.addWidget(title, 1)

        # light/dark switch: just a small sun or moon next to the name
        self.theme_button = QPushButton()
        self.theme_button.setObjectName("ThemeToggle")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.setFixedSize(QSize(32, 32))
        self.theme_button.setIconSize(QSize(18, 18))
        self.theme_button.setFlat(True)
        self.theme_button.clicked.connect(self.toggle_theme)
        brand_row.addWidget(self.theme_button, 0, Qt.AlignVCenter)
        layout.addWidget(brand)

        subtitle = QLabel("Free productivity toolbox")
        subtitle.setObjectName("SidebarSubtitle")
        layout.addWidget(subtitle)
        self.search_input = QLineEdit()
        self.search_input.setObjectName("ToolSearch")
        self.search_input.setPlaceholderText("Find a tool...")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setToolTip("Type a word - pdf, photo, rename, sound... - to see only the tools that match.")
        self.search_input.textChanged.connect(self.filter_tools)
        search_row = QHBoxLayout()
        search_row.setContentsMargins(16, 8, 16, 6)
        search_row.addWidget(self.search_input)
        layout.addLayout(search_row)

        self.tool_list = QListWidget()
        self.tool_list.setObjectName("ToolList")
        self.tool_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tool_list.setTextElideMode(Qt.ElideRight)
        self.tool_list.currentRowChanged.connect(self._on_tool_selected)
        layout.addWidget(self.tool_list, 1)

        version = QLabel(f"v{promak.__version__}  -  MIT licence")
        version.setObjectName("SidebarFooter")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)
        self._refresh_theme_button()
        return sidebar

    # -------------------------------------------------------------- theme
    def _refresh_theme_button(self) -> None:
        going_to = other_theme(self._theme)
        self.theme_button.setIcon(switch_icon(self._theme, palette(self._theme)["text_dim"]))
        self.theme_button.setToolTip(
            ("Dark colours" if going_to == "dark" else "Light colours")
            + "\nPromak remembers your choice for next time."
        )
        self.theme_button.setAccessibleName(f"Switch to {going_to} colours")

    def toggle_theme(self) -> None:
        """Flip between the light and the dark palette, and remember it."""
        self._theme = other_theme(self._theme)
        self.apply_theme(self._theme)
        self.config.set("app.theme", self._theme)
        self.statusBar().showMessage(f"{self._theme.capitalize()} colours", 4000)

    def apply_theme(self, name: str) -> None:
        """Re-skin every open window."""
        self._theme = normalise_theme(name)
        application = QApplication.instance()
        if application is not None:
            application.setStyleSheet(stylesheet(self._theme, self._zoom))
        self._refresh_theme_button()

    # --------------------------------------------------------------- zoom
    def _build_zoom_controls(self) -> None:
        """A - 100 % + in the status bar, and the usual keys to go with it."""
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 6, 0)
        row.setSpacing(4)
        self.zoom_out_button = QPushButton("A-")
        self.zoom_reset_button = QPushButton()
        self.zoom_in_button = QPushButton("A+")
        tips = (
            (self.zoom_out_button, "Smaller letters  (Ctrl -,  or Ctrl + mouse wheel)", -1),
            (self.zoom_reset_button, "Back to the normal size  (Ctrl 0)", 0),
            (self.zoom_in_button, "Bigger letters  (Ctrl +,  or Ctrl + mouse wheel)", 1),
        )
        for button, tip, direction in tips:
            button.setObjectName("ZoomButton")
            button.setToolTip(tip + "\nPromak remembers the size for next time.")
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.clicked.connect(lambda _checked=False, d=direction: self.change_zoom(d))
            row.addWidget(button)
        self.statusBar().addPermanentWidget(holder)
        for keys, direction in ((QKeySequence.ZoomIn, 1), ("Ctrl+=", 1), (QKeySequence.ZoomOut, -1),
                                ("Ctrl+0", 0)):
            shortcut = QShortcut(QKeySequence(keys), self)
            shortcut.setContext(Qt.ApplicationShortcut)
            shortcut.activated.connect(lambda d=direction: self.change_zoom(d))
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        self._refresh_zoom_controls()

    def _refresh_zoom_controls(self) -> None:
        self.zoom_reset_button.setText(f"{round(self._zoom * 100)} %")
        self.zoom_out_button.setEnabled(zoom_step(self._zoom, -1) != self._zoom)
        self.zoom_in_button.setEnabled(zoom_step(self._zoom, 1) != self._zoom)

    def change_zoom(self, direction: int) -> None:
        """Letters one step bigger (1), smaller (-1) or normal (0), everywhere."""
        self.set_zoom(zoom_step(self._zoom, direction))

    def set_zoom(self, value: float) -> None:
        zoom = normalise_zoom(value)
        if zoom == self._zoom:
            return
        self._zoom = zoom
        self.config.set("app.zoom", zoom)
        self.sidebar.setFixedWidth(round(SIDEBAR_WIDTH * zoom))
        self.apply_theme(self._theme)
        self._refresh_zoom_controls()
        self.statusBar().showMessage(f"Letters at {round(zoom * 100)} %", 3000)

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt naming
        """Ctrl + mouse wheel zooms the whole window, wherever the mouse is."""
        if (event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier
                and self.isActiveWindow()):
            delta = event.angleDelta().y()
            if delta:
                self.change_zoom(1 if delta > 0 else -1)
                return True
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------ screen
    @staticmethod
    def _available_size():
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return None
        room = screen.availableGeometry()
        return room.width(), room.height()

    def _fitting_size(self, width: int, height: int):
        """``width`` x ``height``, made smaller when the screen has less room."""
        room = self._available_size()
        if room is None:
            return width, height
        # leave the title bar and a little margin in view
        return (max(MINIMUM_WINDOW[0], min(width, room[0] - 16)),
                max(MINIMUM_WINDOW[1], min(height, room[1] - 40)))

    def _keep_on_screen(self) -> None:
        """A window saved on a bigger screen is brought back inside this one."""
        screen = QGuiApplication.screenAt(self.frameGeometry().center()) or QGuiApplication.primaryScreen()
        if screen is None or self.isMaximized():
            return
        room = screen.availableGeometry()
        frame = self.frameGeometry()
        if room.contains(frame):
            return
        width, height = self._fitting_size(self.width(), self.height())
        self.resize(min(width, room.width() - 16), min(height, room.height() - 40))
        frame = self.frameGeometry()
        x = min(max(room.left(), frame.left()), room.right() - frame.width() + 1)
        y = min(max(room.top(), frame.top()), room.bottom() - frame.height() + 1)
        self.move(max(room.left(), x), max(room.top(), y))

    def _populate_tools(self) -> None:
        tools = registry.discover()
        if not tools:
            placeholder = QLabel("No tool could be loaded.\nCheck the log file for details.")
            placeholder.setAlignment(Qt.AlignCenter)
            self.stack.addWidget(placeholder)
            return

        category = None
        for tool in tools:
            if tool.info.category != category:
                # a heading that cannot be selected, one per group of tools
                category = tool.info.category
                heading = QListWidgetItem(category.upper())
                heading.setFlags(Qt.NoItemFlags)
                heading.setData(HEADING_ROLE, category)
                self.tool_list.addItem(heading)
            label = f"  {tool.info.icon}  {tool.info.name}".rstrip()
            item = QListWidgetItem(label)
            item.setToolTip(tool.info.summary)
            item.setData(Qt.UserRole, tool.info.id)
            item.setData(SEARCH_ROLE, " ".join((tool.info.name, tool.info.summary, tool.info.category,
                                                *tool.info.tags)).casefold())
            item.setData(HEADING_ROLE, None)
            self.tool_list.addItem(item)
            widget = tool.create_widget(self)
            self._pages[tool.info.id] = self.stack.addWidget(widget)

        last = self.config.get("app.last_tool")
        rows = self.tool_rows()
        index = next((row for row in rows if self.tool_list.item(row).data(Qt.UserRole) == last), rows[0])
        self.tool_list.setCurrentRow(index)

    def tool_rows(self) -> List[int]:
        """The rows of the sidebar that are tools (not group headings)."""
        return [row for row in range(self.tool_list.count())
                if self.tool_list.item(row).data(Qt.UserRole)]

    def filter_tools(self, text: str) -> None:
        """Show only the tools whose name, summary or keywords hold every word typed."""
        words = text.casefold().split()
        shown_in = set()
        for row in self.tool_rows():
            item = self.tool_list.item(row)
            haystack = item.data(SEARCH_ROLE) or ""
            visible = all(word in haystack for word in words)
            item.setHidden(not visible)
            if visible:
                shown_in.add(self._category_of(row))
        for row in range(self.tool_list.count()):
            item = self.tool_list.item(row)
            category = item.data(HEADING_ROLE)
            if category:
                item.setHidden(category not in shown_in)

    def _category_of(self, row: int) -> str:
        for above in range(row, -1, -1):
            category = self.tool_list.item(above).data(HEADING_ROLE)
            if category:
                return category
        return ""

    def _on_tool_selected(self, row: int) -> None:
        item = self.tool_list.item(row)
        if item is None or not item.data(Qt.UserRole):
            return
        tool_id = item.data(Qt.UserRole)
        self.stack.setCurrentIndex(self._pages.get(tool_id, 0))
        self.config.set("app.last_tool", tool_id)

    # ---------------------------------------------------------- geometry
    def _restore_geometry(self) -> None:
        saved = self.config.get("app.window_geometry")
        if saved:
            try:
                self.restoreGeometry(QByteArray.fromBase64(saved.encode("ascii")))
            except Exception:  # pragma: no cover
                pass
        self._keep_on_screen()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        busy = [
            tool for tool in registry.tools
            if getattr(tool, "has_running_work", lambda: False)()
        ]
        if busy:
            answer = QMessageBox.question(
                self,
                "Work in progress",
                "A conversion is still running. Quit anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        try:
            self.config.set(
                "app.window_geometry",
                bytes(self.saveGeometry().toBase64()).decode("ascii"),
            )
        except Exception:  # pragma: no cover
            pass
        registry.shutdown()
        event.accept()
