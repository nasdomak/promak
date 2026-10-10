"""Registration of the screen recorder as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class ScreenRecorderTool(PanelTool):
    info = ToolInfo(
        id="screenrec",
        name="Screen recorder",
        summary="Film the screen or a part of it into an MP4, with Start and Stop.",
        category="Video and sound",
        icon="◉",
        order=18,
        tags=("screen", "record", "capture", "tutorial", "video", "screencast"),
    )
    panel = "promak.tools.screenrec.panel:ScreenRecorderPanel"


PROMAK_TOOL = ScreenRecorderTool
