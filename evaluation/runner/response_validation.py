"""Minimal MCP response schema validation."""

from __future__ import annotations

from typing import Any


COLLECT_REQUIRED_FIELDS = {
    "schema_version",
    "status",
    "evidenceItem",
    "coverage",
}

ANALYZE_REQUIRED_FIELDS = {
    "summary",
    "status",
    "recommendations",
    "report_markdown",
}


def validate_response(tool: str, response: dict[str, Any]) -> list[str]:
    """Return missing required fields for a tool response."""

    normalized_tool = tool.lower()
    if normalized_tool in {"collect", "collect_competitor_intelligence"}:
        required = COLLECT_REQUIRED_FIELDS
    elif normalized_tool in {"analyze", "analyze_competition"}:
        required = ANALYZE_REQUIRED_FIELDS
    else:
        return [f"unsupported tool: {tool}"]

    return [field for field in required if field not in response]
