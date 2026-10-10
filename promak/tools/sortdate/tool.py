"""Registration of the photo sorter as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class SortDateTool(PanelTool):
    info = ToolInfo(
        id="sortdate",
        name="Sort photos by date",
        summary="Move or copy photos and videos into YYYY/MM - Month folders, by the date they were taken.",
        category="Files and folders",
        icon="▦",
        order=73,
        tags=("sort", "date", "photos", "videos", "exif", "folders", "organise"),
    )
    panel = "promak.tools.sortdate.panel:SortDatePanel"


PROMAK_TOOL = SortDateTool
