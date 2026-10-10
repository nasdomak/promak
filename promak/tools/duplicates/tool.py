"""Registration of the duplicate finder as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class DuplicatesTool(PanelTool):
    info = ToolInfo(
        id="duplicates",
        name="Find duplicates",
        summary="Find exact copies and similar pictures; keep the best, bin or move the others.",
        category="Files and folders",
        icon="⧉",
        order=72,
        tags=("duplicates", "copies", "similar", "photos", "clean", "space"),
    )
    panel = "promak.tools.duplicates.panel:DuplicatesPanel"


PROMAK_TOOL = DuplicatesTool
