"""Registration of the GIF and collage maker as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class GifCollageTool(PanelTool):
    info = ToolInfo(
        id="gifcollage",
        name="GIF and collage",
        summary="Pictures into an animated GIF or WEBP, or into a collage grid.",
        category="Pictures",
        icon="▧",
        order=36,
        tags=("gif", "animation", "collage", "grid", "webp", "slideshow"),
    )
    panel = "promak.tools.gifcollage.panel:GifCollagePanel"


PROMAK_TOOL = GifCollageTool
