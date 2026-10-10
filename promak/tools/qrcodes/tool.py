"""Registration of the QR code and barcode maker as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class QrCodesTool(PanelTool):
    info = ToolInfo(
        id="qrcodes",
        name="QR codes and barcodes",
        summary="QR codes for links, texts and Wi-Fi, and barcodes - one or a whole list, as PNG or SVG.",
        category="Pictures",
        icon="▣",
        order=38,
        tags=("qr", "barcode", "ean", "code128", "wifi", "svg", "label"),
    )
    panel = "promak.tools.qrcodes.panel:QrCodesPanel"


PROMAK_TOOL = QrCodesTool
