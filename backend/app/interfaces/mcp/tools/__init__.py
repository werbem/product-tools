"""MCP tool registration modules."""

from app.interfaces.mcp.tools.analyze_competition_tool import (
    register_analyze_competition_tool,
)
from app.interfaces.mcp.tools.collect_intelligence_tool import (
    register_collect_intelligence_tool,
)

__all__ = [
    "register_analyze_competition_tool",
    "register_collect_intelligence_tool",
]
