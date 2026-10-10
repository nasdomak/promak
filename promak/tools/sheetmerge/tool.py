"""Registration of the spreadsheet merger as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class SheetMergeTool(PanelTool):
    info = ToolInfo(
        id="sheetmerge",
        name="Merge spreadsheets",
        summary="Many CSV and Excel files into one table, columns matched by name, with the source of each row.",
        category="Documents",
        icon="⊞",
        order=56,
        tags=("merge", "excel", "csv", "xlsx", "combine", "table", "spreadsheet"),
    )
    panel = "promak.tools.sheetmerge.panel:SheetMergePanel"


PROMAK_TOOL = SheetMergeTool
