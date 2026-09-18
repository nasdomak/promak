"""Registration of the picture shrinker as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PromakTool, ToolInfo


class ShrinkTool(PromakTool):
    info = ToolInfo(
        id="shrink",
        name="Make pictures lighter",
        summary="Squeeze JPG, PNG, WEBP and TIFF files without changing their format.",
        category="Pictures",
        icon="⬇",
        order=30,
        tags=("images", "compress", "jpeg", "png", "web"),
    )

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        from promak.tools.shrink.panel import ShrinkPanel

        if self._widget is None:
            self._widget = ShrinkPanel(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None:
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        return bool(self._widget and self._widget.has_running_work())


PROMAK_TOOL = ShrinkTool
