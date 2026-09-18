"""Registration of the video downloader as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PromakTool, ToolInfo


class VideoTool(PromakTool):
    info = ToolInfo(
        id="video",
        name="Video downloader",
        summary="Download a video from almost any site, extract the MP3 and transcribe it.",
        category="Media",
        icon="▶",
        order=10,
        tags=("video", "audio", "transcription", "download"),
    )

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        from promak.tools.video.panel import VideoPanel

        if self._widget is None:
            self._widget = VideoPanel(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None:
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        return bool(self._widget and self._widget.has_running_work())


PROMAK_TOOL = VideoTool
