"""Registration of offline translation as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class TranslateTool(PanelTool):
    info = ToolInfo(
        id="translate",
        name="Translate (offline)",
        summary="Translate text files and subtitles on this computer; language packs downloaded once.",
        category="Documents",
        icon="⇋",
        order=59,
        tags=("translate", "translation", "language", "italian", "english", "subtitles", "offline"),
    )
    panel = "promak.tools.translate.panel:TranslatePanel"


PROMAK_TOOL = TranslateTool
