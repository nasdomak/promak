"""Registration of the subtitle burner as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class SubtitlesTool(PanelTool):
    info = ToolInfo(
        id="subtitles",
        name="Burn subtitles",
        summary="Draw SRT or VTT subtitles into the picture of a video, so they show on every player.",
        category="Video and sound",
        icon="⌨",
        order=16,
        tags=("subtitles", "srt", "vtt", "captions", "video", "burn", "transcript"),
    )
    panel = "promak.tools.subtitles.panel:SubtitlesPanel"


PROMAK_TOOL = SubtitlesTool
