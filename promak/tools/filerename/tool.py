"""Registration of the batch file renamer as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class FileRenameTool(PanelTool):
    info = ToolInfo(
        id="filerename",
        name="Rename files",
        summary="Rename many files with a code - number, old name, date taken, size - with a preview and undo.",
        category="Files and folders",
        icon="✎",
        order=71,
        tags=("rename", "files", "batch", "photos", "exif", "date"),
    )
    panel = "promak.tools.filerename.panel:FileRenamerPanel"


PROMAK_TOOL = FileRenameTool
