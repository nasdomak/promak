"""The application shell: sidebar of tools plus the active tool page."""

from __future__ import annotations

import logging
from typing import Dict, List

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QPixmap
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
from promak.ui.theme import other_theme, palette, stylesheet
from promak.ui.theme_icons import switch_icon

log = logging.getLogger(__name__)

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

        self.setWindowTitle(f"Promak {promak.__version__}")
        # three columns side by side need some width
        self.setMinimumSize(1180, 700)
        self.resize(1440, 880)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._build_sidebar())

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)

        self._populate_tools()
        self._restore_geometry()
        self.statusBar().showMessage("Ready")

    # ----------------------------------------------------------- sidebar
    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(232)
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
            application.setStyleSheet(stylesheet(self._theme))
        self._refresh_theme_button()

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
