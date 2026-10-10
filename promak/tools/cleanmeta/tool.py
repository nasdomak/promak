"""Registration of the hidden-data remover as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class CleanMetaTool(PanelTool):
    info = ToolInfo(
        id="cleanmeta",
        name="Remove hidden data",
        summary="See and remove GPS, camera and author data from photos, PDF and Office files before sharing them.",
        category="Files and folders",
        icon="⊘",
        order=74,
        tags=("privacy", "exif", "gps", "metadata", "author", "clean", "share"),
    )
    panel = "promak.tools.cleanmeta.panel:CleanMetaPanel"


PROMAK_TOOL = CleanMetaTool
