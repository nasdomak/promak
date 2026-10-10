"""Registration of the background remover as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class BackgroundTool(PanelTool):
    info = ToolInfo(
        id="background",
        name="Remove background",
        summary="Cut out people and products: transparent PNG or a solid colour, on this computer.",
        category="Pictures",
        icon="◐",
        order=35,
        tags=("background", "remove", "cut out", "transparent", "product", "portrait", "ai"),
    )
    panel = "promak.tools.background.panel:BackgroundPanel"


PROMAK_TOOL = BackgroundTool
