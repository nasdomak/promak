"""Registration of the OCR tool as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class OcrTool(PanelTool):
    info = ToolInfo(
        id="ocr",
        name="Text from pictures",
        summary="Read the text in pictures and scanned PDFs (OCR) - text files or searchable PDFs, offline.",
        category="Documents",
        icon="⌕",
        order=52,
        tags=("ocr", "scan", "text", "searchable", "pdf", "recognise", "read"),
    )
    panel = "promak.tools.ocr.panel:OcrPanel"


PROMAK_TOOL = OcrTool
