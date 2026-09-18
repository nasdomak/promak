"""The application shell: sidebar of tools plus the active tool page."""

from __future__ import annotations

import logging
from typing import Dict

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
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
from promak.ui.theme import other_theme, stylesheet

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Hosts every Promak tool behind one window."""

    def __init__(self) -> None:
        super().__init__()
        self.config = get_config()
        self._pages: Dict[str, int] = {}
        self._theme = normalise_theme(self.config.get("app.theme"))

        self.setWindowTitle(f"Promak {promak.__version__}")
        self.setMinimumSize(1040, 720)
        self.resize(1240, 860)

        central = QWidget()
        self.setCentralWidget(central)
        from PySide6.QtWidgets import QHBoxLayout

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
        layout.addWidget(brand)

        subtitle = QLabel("Free productivity toolbox")
        subtitle.setObjectName("SidebarSubtitle")
        section = QLabel("TOOLS")
        section.setObjectName("SidebarSection")
        layout.addWidget(subtitle)
        layout.addWidget(section)

        self.tool_list = QListWidget()
        self.tool_list.setObjectName("ToolList")
        self.tool_list.currentRowChanged.connect(self._on_tool_selected)
        layout.addWidget(self.tool_list, 1)

        self.theme_button = QPushButton()
        self.theme_button.setObjectName("ThemeToggle")
        self.theme_button.setCursor(Qt.PointingHandCursor)
        self.theme_button.clicked.connect(self.toggle_theme)
        button_row = QHBoxLayout()
        button_row.setContentsMargins(12, 4, 12, 6)
        button_row.addWidget(self.theme_button)
        layout.addLayout(button_row)

        version = QLabel(f"v{promak.__version__}  -  MIT licence")
        version.setObjectName("SidebarFooter")
        version.setAlignment(Qt.AlignCenter)
        layout.addWidget(version)
        self._refresh_theme_button()
        return sidebar

    # -------------------------------------------------------------- theme
    def _refresh_theme_button(self) -> None:
        going_to = other_theme(self._theme)
        self.theme_button.setText(
            "Switch to dark colours" if going_to == "dark" else "Switch to light colours"
        )
        self.theme_button.setToolTip(
            "Changes the colours of the whole window straight away.\n"
            "Promak remembers your choice for next time."
        )

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

        for tool in tools:
            label = f"  {tool.info.icon}  {tool.info.name}".rstrip()
            item = QListWidgetItem(label)
            item.setToolTip(tool.info.summary)
            item.setData(Qt.UserRole, tool.info.id)
            self.tool_list.addItem(item)
            widget = tool.create_widget(self)
            self._pages[tool.info.id] = self.stack.addWidget(widget)

        last = self.config.get("app.last_tool")
        index = next(
            (row for row in range(self.tool_list.count())
             if self.tool_list.item(row).data(Qt.UserRole) == last),
            0,
        )
        self.tool_list.setCurrentRow(index)

    def _on_tool_selected(self, row: int) -> None:
        item = self.tool_list.item(row)
        if item is None:
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
