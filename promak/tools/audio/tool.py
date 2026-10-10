"""Registration of the audio toolbox as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PromakTool, ToolInfo


class AudioTool(PromakTool):
    info = ToolInfo(
        id="audio",
        name="Audio toolbox",
        summary="Convert, even out the volume, trim and split sound files - also the sound of videos.",
        category="Video and sound",
        icon="♪",
        order=14,
        tags=("audio", "mp3", "convert", "normalise", "split"),
    )

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        from promak.tools.audio.panel import AudioPanel

        if self._widget is None:
            self._widget = AudioPanel(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None:
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        return bool(self._widget and self._widget.has_running_work())


PROMAK_TOOL = AudioTool
