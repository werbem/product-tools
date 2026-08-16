"""Call MCP tool logic directly through the existing MCP adapters."""

from __future__ import annotations

from typing import Any

from app.interfaces.mcp.adapters import (
    AnalysisRunner,
    AnalyzeInputAdapter,
    AnalyzeOutputAdapter,
    CollectInputAdapter,
    CollectOutputAdapter,
    WorkflowRunner,
)
from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionInput,
    CollectCompetitorIntelligenceInput,
)


class DirectToolInvoker:
    """Execute the same adapter path as the MCP tool handlers.

    This runner intentionally avoids requiring the optional ``mcp`` transport
    package so the evaluation framework can run in the same environment as the
    service.
    """

    async def invoke(self, case: dict[str, Any]) -> dict[str, Any]:
        tool = case.get("tool", "")
        if tool in {"collect", "collect_competitor_intelligence"}:
            return await self._invoke_collect(case)
        if tool in {"analyze", "analyze_competition"}:
            return await self._invoke_analyze(case)
        raise ValueError(f"unsupported tool: {tool}")

    async def _invoke_collect(self, case: dict[str, Any]) -> dict[str, Any]:
        payload = CollectCompetitorIntelligenceInput(**case.get("input", {}))
        state = CollectInputAdapter().to_initial_state(payload)
        internal_state = await WorkflowRunner().run_collect(state)
        output = CollectOutputAdapter().from_internal_state(
            internal_state,
            max_evidence=payload.max_evidence,
        )
        return output.model_dump()

    async def _invoke_analyze(self, case: dict[str, Any]) -> dict[str, Any]:
        input_data = dict(case.get("input", {}))
        if "intelligence" in case and "intelligence" not in input_data:
            input_data["intelligence"] = case["intelligence"]
        if "output_level" in case and "output_level" not in input_data:
            input_data["output_level"] = case["output_level"]

        payload = AnalyzeCompetitionInput(**input_data)

        if payload.intelligence is None:
            collect_state = CollectInputAdapter().to_initial_state(
                CollectCompetitorIntelligenceInput(
                    our_company=payload.our_company,
                    competitor_company=payload.competitor_company,
                    product=payload.product,
                    objective=payload.objective,
                )
            )
            collect_internal = await WorkflowRunner().run_collect(collect_state)
            analysis_state = collect_internal
        else:
            analysis_state = AnalyzeInputAdapter().to_internal_state(payload)

        internal_result = await AnalysisRunner().run(analysis_state)
        output = AnalyzeOutputAdapter().from_internal_state(
            internal_result,
            output_level=payload.output_level,
        )
        return output.model_dump()
