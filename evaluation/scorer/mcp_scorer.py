"""Rule-based MCP-level metrics."""

from __future__ import annotations

from typing import Any


def _latency_score(latency_ms: float) -> float:
    if latency_ms <= 3000:
        return 1.0
    if latency_ms <= 10000:
        return 0.7
    if latency_ms <= 30000:
        return 0.4
    return 0.1


def score_mcp(result: dict[str, Any]) -> dict[str, Any]:
    latency = float(result.get("execution_time", 0) or 0)
    failure_rate = 0.0 if result.get("status") == "passed" else 1.0
    schema_validation = 1.0 if not result.get("missing_fields") else 0.0
    latency_score = _latency_score(latency)
    total_score = round(
        (latency_score + (1 - failure_rate) + schema_validation) / 3,
        3,
    )
    return {
        "latency": latency,
        "latency_score": latency_score,
        "failure_rate": failure_rate,
        "schema_validation": schema_validation,
        "total_score": total_score,
    }
