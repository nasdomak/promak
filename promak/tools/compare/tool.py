"""Registration of the folder comparison as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class CompareTool(PanelTool):
    info = ToolInfo(
        id="compare",
        name="Compare two folders",
        summary="See what is only on one side, what differs and what is identical; copy the missing files across.",
        category="Files and folders",
        icon="⇆",
        order=76,
        tags=("compare", "folders", "backup", "sync", "missing", "difference"),
    )
    panel = "promak.tools.compare.panel:ComparePanel"


PROMAK_TOOL = CompareTool
