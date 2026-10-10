"""Registration of the watched folder as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class WatchTool(PanelTool):
    info = ToolInfo(
        id="watch",
        name="Watched folder",
        summary="Every new file of a folder goes through a tool or a recipe into an output folder.",
        category="Automation",
        icon="◎",
        order=91,
        tags=("watch", "folder", "automatic", "hot folder", "scanner", "automation"),
    )
    panel = "promak.tools.watch.panel:WatchPanel"


PROMAK_TOOL = WatchTool
