"""Registration of the batch picture tool as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PromakTool, ToolInfo


class PictureBatchTool(PromakTool):
    info = ToolInfo(
        id="picturebatch",
        name="Resize and convert",
        summary="Resize, convert and watermark many pictures in one go.",
        category="Pictures",
        icon="⤢",
        order=34,
        tags=("images", "resize", "convert", "watermark", "batch"),
    )

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        from promak.tools.picturebatch.panel import PictureBatchPanel

        if self._widget is None:
            self._widget = PictureBatchPanel(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None:
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        return bool(self._widget and self._widget.has_running_work())


PROMAK_TOOL = PictureBatchTool
