"""Registration of Books to Markdown as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class BookNotesTool(PanelTool):
    info = ToolInfo(
        id="booknotes",
        name="Books to Markdown",
        summary="Books and documents (PDF, EPUB, Word, slides...) into light Markdown notes with their "
                "pictures, for an AI or a second brain. Scanned pages read with the offline OCR.",
        category="Documents",
        icon="❡",
        order=55,
        tags=("book", "pdf", "epub", "markdown", "notes", "obsidian", "second brain", "ai", "chatgpt",
              "ocr", "scan", "pictures", "chapters", "docx", "pptx"),
    )
    panel = "promak.tools.booknotes.panel:BookNotesPanel"


PROMAK_TOOL = BookNotesTool
