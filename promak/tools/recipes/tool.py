"""Registration of recipes as a Promak tool."""

from __future__ import annotations

from promak.core.tool_registry import PanelTool, ToolInfo


class RecipesTool(PanelTool):
    info = ToolInfo(
        id="recipes",
        name="Recipes",
        summary="Save a chain of steps from the other tools and run it with one click or from the command line.",
        category="Automation",
        icon="☰",
        order=90,
        tags=("recipe", "chain", "steps", "automation", "batch", "workflow"),
    )
    panel = "promak.tools.recipes.panel:RecipesPanel"


PROMAK_TOOL = RecipesTool
