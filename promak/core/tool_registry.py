"""Plugin system for Promak tools.

A tool is a package under ``promak.tools`` that exposes a module-level
``PROMAK_TOOL`` pointing at a :class:`PromakTool` subclass.  Dropping a
new package in that folder is enough to make it appear in the sidebar -
no other file has to be edited.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Type

log = logging.getLogger(__name__)

#: the tools shipped with Promak, used when the folder cannot be listed
BUILT_IN_TOOLS = (
    "video", "videotools", "vectorize", "shrink", "picturebatch", "audio", "text", "renamer",
    "pdf", "filerename", "duplicates", "sortdate", "ocr", "docconvert",
    "sheetmerge", "cleanmeta", "qrcodes", "gifcollage",
    "subtitles", "silence", "archives", "compare",
    "shred", "background", "screenrec",
)


@dataclass(frozen=True)
class ToolInfo:
    """Everything the shell needs to show a tool before loading it."""

    id: str
    name: str
    summary: str
    category: str = "General"
    icon: str = ""          # single character / emoji used in the sidebar
    order: int = 100        # lower sorts first
    enabled: bool = True
    tags: tuple = field(default_factory=tuple)


class PromakTool(ABC):
    """Base class every Promak tool inherits from."""

    info: ToolInfo

    @abstractmethod
    def create_widget(self, parent=None):
        """Return the QWidget shown when the tool is selected."""

    def shutdown(self) -> None:  # noqa: B027 - optional on purpose
        """Release resources before the application quits."""


class PanelTool(PromakTool):
    """A tool whose whole job is showing one screen.

    Most tools only differ by their :class:`ToolInfo` and the screen they
    show, so they say where the screen lives (``"package.module:Class"``)
    and this class creates it the first time it is needed, keeps it, and
    forwards ``shutdown`` and ``has_running_work`` to it.
    """

    panel: str = ""

    def __init__(self) -> None:
        self._widget = None

    def create_widget(self, parent=None):
        if self._widget is None:
            module_name, _, class_name = self.panel.partition(":")
            panel_cls = getattr(importlib.import_module(module_name), class_name)
            self._widget = panel_cls(parent)
        return self._widget

    def shutdown(self) -> None:
        if self._widget is not None and hasattr(self._widget, "shutdown"):
            self._widget.shutdown()

    def has_running_work(self) -> bool:
        checker = getattr(self._widget, "has_running_work", None)
        return bool(checker and checker())


class ToolRegistry:
    """Discovers and instantiates the available tools."""

    def __init__(self) -> None:
        self._tools: List[PromakTool] = []

    def discover(self) -> List[PromakTool]:
        if self._tools:
            return self._tools

        import promak.tools as tools_pkg

        found: List[PromakTool] = []
        names = [m.name for m in pkgutil.iter_modules(tools_pkg.__path__)
                 if m.ispkg and not m.name.startswith("_")]
        if not names:
            # an installed (frozen) copy may hide its folders from pkgutil
            names = list(BUILT_IN_TOOLS)
        for name in names:
            dotted = f"{tools_pkg.__name__}.{name}.tool"
            try:
                module = importlib.import_module(dotted)
            except Exception as exc:
                log.exception("Tool '%s' could not be loaded: %s", name, exc)
                continue

            tool_cls: Optional[Type[PromakTool]] = getattr(module, "PROMAK_TOOL", None)
            if tool_cls is None:
                log.warning("Tool '%s' has no PROMAK_TOOL attribute; skipped.", dotted)
                continue
            try:
                instance = tool_cls()
            except Exception as exc:
                log.exception("Tool '%s' could not be created: %s", dotted, exc)
                continue
            if getattr(instance.info, "enabled", True):
                found.append(instance)

        found.sort(key=lambda t: (t.info.order, t.info.name.lower()))
        self._tools = found
        log.info("Loaded %d tool(s): %s", len(found), ", ".join(t.info.id for t in found))
        return self._tools

    @property
    def tools(self) -> List[PromakTool]:
        return list(self._tools)

    def shutdown(self) -> None:
        for tool in self._tools:
            try:
                tool.shutdown()
            except Exception:  # pragma: no cover
                log.exception("Error while shutting down tool %s", tool.info.id)


registry = ToolRegistry()
