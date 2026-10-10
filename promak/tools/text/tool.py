"""Registration of the text toolbox as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PromakTool, ToolInfo


class TextTool(PromakTool):
    info = ToolInfo(
        id="text",
        name="Text toolbox",
        summary="Clean up, summarise and convert text files and subtitles - offline.",
        category="Documents",
        icon="¶",
        order=58,
        tags=("text", "summary", "clean", "subtitles", "markdown"),
    )

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        from promak.tools.text.panel import TextPanel

        if self._widget is None:
            self._widget = TextPanel(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None:
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        return bool(self._widget and self._widget.has_running_work())


PROMAK_TOOL = TextTool
