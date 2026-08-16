"""Execute internal LangGraph workflows from MCP handlers.

Phase 1 defines the boundary only. Subgraph selection and state construction
are intentionally deferred so existing Web API behavior is not affected yet.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.interfaces.mcp.adapters.reliability import COLLECT_TIMEOUT_SECONDS


class WorkflowRunner:
    """Run collect or analyze workflows without exposing LangGraph internals."""

    async def run_collect(self, state: dict[str, Any]) -> dict[str, Any]:
        from app.infrastructure.workflow.collect_graph import collect_graph

        return await asyncio.wait_for(
            collect_graph.ainvoke(state),
            timeout=COLLECT_TIMEOUT_SECONDS,
        )

    async def run_analysis(self, internal_payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("analysis_subgraph is wired in Phase 2")
