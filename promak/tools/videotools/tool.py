"""Registration of the videotools toolbox as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PromakTool, ToolInfo


class VideoToolsTool(PromakTool):
    info = ToolInfo(
        id="videotools",
        name="Video toolbox",
        summary="Convert, compress and trim videos, or take pictures out of them.",
        category="Video and sound",
        icon="✂",
        order=12,
        tags=("video", "mp4", "compress", "trim", "frames"),
    )

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        from promak.tools.videotools.panel import VideoToolsPanel

        if self._widget is None:
            self._widget = VideoToolsPanel(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None:
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        return bool(self._widget and self._widget.has_running_work())


PROMAK_TOOL = VideoToolsTool
