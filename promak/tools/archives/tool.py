"""Registration of the archive tool as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class ArchivesTool(PanelTool):
    info = ToolInfo(
        id="archives",
        name="Archives",
        summary="Make ZIP (with an AES password) and 7z archives; list and extract ZIP, 7z and TAR safely.",
        category="Files and folders",
        icon="◫",
        order=75,
        tags=("zip", "7z", "tar", "archive", "compress", "extract", "unzip", "password"),
    )
    panel = "promak.tools.archives.panel:ArchivesPanel"


PROMAK_TOOL = ArchivesTool
