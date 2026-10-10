"""Registration of the silence cutter as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class SilenceTool(PanelTool):
    info = ToolInfo(
        id="silence",
        name="Cut silences",
        summary="Remove the silent parts from lectures, podcasts and recordings - sound or video.",
        category="Video and sound",
        icon="⏵",
        order=17,
        tags=("silence", "pauses", "podcast", "lecture", "audio", "video", "shorter"),
    )
    panel = "promak.tools.silence.panel:SilencePanel"


PROMAK_TOOL = SilenceTool
