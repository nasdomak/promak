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

    def shutdown(self) -> None:
        """Release resources before the application quits."""


class ToolRegistry:
    """Discovers and instantiates the available tools."""

    def __init__(self) -> None:
        self._tools: List[PromakTool] = []

    def discover(self) -> List[PromakTool]:
        if self._tools:
            return self._tools

        import promak.tools as tools_pkg

        found: List[PromakTool] = []
        for module_info in pkgutil.iter_modules(tools_pkg.__path__):
            if not module_info.ispkg or module_info.name.startswith("_"):
                continue
            dotted = f"{tools_pkg.__name__}.{module_info.name}.tool"
            try:
                module = importlib.import_module(dotted)
            except Exception as exc:
                log.exception("Tool '%s' could not be loaded: %s", module_info.name, exc)
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
