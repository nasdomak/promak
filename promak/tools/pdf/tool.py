"""Registration of the PDF toolbox as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class PdfTool(PanelTool):
    info = ToolInfo(
        id="pdf",
        name="PDF toolbox",
        summary="Merge, split, rotate, compress and protect PDF files; pictures to PDF and back.",
        category="Documents",
        icon="▤",
        order=50,
        tags=("pdf", "merge", "split", "rotate", "compress", "password"),
    )
    panel = "promak.tools.pdf.panel:PdfPanel"


PROMAK_TOOL = PdfTool
