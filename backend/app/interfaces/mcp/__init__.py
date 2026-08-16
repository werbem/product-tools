"""MCP interface package for Competitive Intelligence MCP.

The server entrypoint is intentionally not imported eagerly here. Import
``app.interfaces.mcp.server`` directly when the optional ``mcp`` runtime is
installed.
"""

from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionInput,
    AnalyzeCompetitionOutput,
    CollectCompetitorIntelligenceInput,
    CollectCompetitorIntelligenceOutput,
    MCP_SCHEMA_VERSION,
)

__all__ = [
    "AnalyzeCompetitionInput",
    "AnalyzeCompetitionOutput",
    "CollectCompetitorIntelligenceInput",
    "CollectCompetitorIntelligenceOutput",
    "MCP_SCHEMA_VERSION",
]
