"""Registration for analyze_competition."""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from app.interfaces.mcp.adapters import (
    AnalysisRunner,
    AnalyzeInputAdapter,
    AnalyzeOutputAdapter,
    CollectInputAdapter,
    WorkflowRunner,
)
from app.interfaces.mcp.adapters.reliability import run_with_retry
from app.interfaces.mcp.errors import MCPErrorCode
from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionInput,
    AnalyzeCompetitionOutput,
    CollectCompetitorIntelligenceInput,
)


ANALYZE_TOOL_NAME = "analyze_competition"
ANALYZE_TOOL_DESCRIPTION = (
    "Help the caller complete a competitive analysis report for a product "
    "against a competitor. It does not provide long-term competitor monitoring "
    "or automatic change tracking."
)


def register_analyze_competition_tool(mcp: FastMCP) -> None:
    """Register the analysis tool on the provided FastMCP instance."""

    @mcp.tool(name=ANALYZE_TOOL_NAME, description=ANALYZE_TOOL_DESCRIPTION)
    async def analyze_competition(
        input: AnalyzeCompetitionInput,
    ) -> AnalyzeCompetitionOutput:
        """Run analysis, collecting evidence first when intelligence is absent."""

        in_collect_phase = False
        try:
            if input.intelligence is None:
                in_collect_phase = True
                collect_state = CollectInputAdapter().to_initial_state(
                    CollectCompetitorIntelligenceInput(
                        our_company=input.our_company,
                        competitor_company=input.competitor_company,
                        product=input.product,
                        objective=input.objective,
                    )
                )
                collect_internal = await run_with_retry(
                    lambda: WorkflowRunner().run_collect(collect_state)
                )
                if collect_internal.get("current_phase") == "collection_failed":
                    return _error_output(
                        MCPErrorCode.COLLECT_RUNTIME_ERROR,
                        "collection failed",
                    )
                analysis_state = collect_internal
            else:
                analysis_state = AnalyzeInputAdapter().to_internal_state(input)

            in_collect_phase = False
            internal_result = await run_with_retry(
                lambda: AnalysisRunner().run(analysis_state)
            )
            return AnalyzeOutputAdapter().from_internal_state(
                internal_result,
                output_level=input.output_level,
            )
        except ValidationError as exc:
            return _error_output(MCPErrorCode.ANALYSIS_INVALID_INPUT, str(exc))
        except TimeoutError as exc:
            code = MCPErrorCode.COLLECT_TIMEOUT if in_collect_phase else MCPErrorCode.ANALYSIS_TIMEOUT
            return _error_output(code, str(exc))
        except Exception as exc:
            code = MCPErrorCode.COLLECT_RUNTIME_ERROR if in_collect_phase else MCPErrorCode.ANALYSIS_RUNTIME_ERROR
            return _error_output(code, f"{type(exc).__name__}: {exc}")

    def _error_output(
        code: MCPErrorCode,
        message: str,
    ) -> AnalyzeCompetitionOutput:
        return AnalyzeCompetitionOutput(
            summary="analysis failed",
            status="failed",
            error_code=code.value,
            message=message,
        )
