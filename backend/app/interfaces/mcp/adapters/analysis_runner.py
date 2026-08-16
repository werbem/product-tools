"""Run the existing analysis nodes without modifying the workflow graph."""

from __future__ import annotations

import asyncio
from typing import Any

from app.interfaces.mcp.adapters.reliability import ANALYSIS_TIMEOUT_SECONDS
from app.infrastructure.workflow.nodes import (
    compare_node,
    finalize_node,
    insight_node,
    report_node,
    review_node,
    strategy_node,
)


class AnalysisRunner:
    """Execute the existing analysis node chain from a prepared state."""

    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.wait_for(
            self._run_nodes(state),
            timeout=ANALYSIS_TIMEOUT_SECONDS,
        )

    async def _run_nodes(self, state: dict[str, Any]) -> dict[str, Any]:
        current = dict(state)
        for node in (
            compare_node,
            insight_node,
            strategy_node,
            report_node,
            review_node,
            finalize_node,
        ):
            update = await node(current)
            current.update(update)
        return current
