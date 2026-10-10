"""Registration of the document converter as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class DocConvertTool(PanelTool):
    info = ToolInfo(
        id="docconvert",
        name="Convert documents",
        summary="Word to text, Markdown or HTML and back; Excel to CSV and back; Office files to PDF.",
        category="Documents",
        icon="⇄",
        order=54,
        tags=("convert", "word", "docx", "markdown", "excel", "xlsx", "csv", "pdf", "html"),
    )
    panel = "promak.tools.docconvert.panel:DocConvertPanel"


PROMAK_TOOL = DocConvertTool
