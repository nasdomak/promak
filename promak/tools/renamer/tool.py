"""Registration of the sequential folder renamer as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PromakTool, ToolInfo


class RenamerTool(PromakTool):
    info = ToolInfo(
        id="renamer",
        name="Number folders",
        summary="Give the folders inside a folder names in sequence: 01, 02, 03...",
        category="Files and folders",
        icon="№",
        order=70,
        tags=("folders", "rename", "sequence", "numbering"),
    )

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        from promak.tools.renamer.panel import RenamerPanel

        if self._widget is None:
            self._widget = RenamerPanel(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None:
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        return False


PROMAK_TOOL = RenamerTool
