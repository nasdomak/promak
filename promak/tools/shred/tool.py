"""Registration of secure delete as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class ShredTool(PanelTool):
    info = ToolInfo(
        id="shred",
        name="Secure delete",
        summary="Overwrite files with random data, then delete them, so they cannot be recovered.",
        category="Files and folders",
        icon="✖",
        order=79,
        tags=("delete", "shred", "wipe", "erase", "privacy", "secure"),
    )
    panel = "promak.tools.shred.panel:ShredPanel"


PROMAK_TOOL = ShredTool
