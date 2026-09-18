"""Registration of the vectoriser as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PromakTool, ToolInfo


class VectorizeTool(PromakTool):
    info = ToolInfo(
        id="vectorize",
        name="Picture to vector",
        summary="Redraw a logo or a drawing as real shapes (SVG), so it never goes blurry.",
        category="Pictures",
        icon="◆",
        order=20,
        tags=("svg", "vector", "logo", "images"),
    )

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        from promak.tools.vectorize.panel import VectorizePanel

        if self._widget is None:
            self._widget = VectorizePanel(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None:
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        return bool(self._widget and self._widget.has_running_work())


PROMAK_TOOL = VectorizeTool
