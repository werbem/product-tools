"""Registration for collect_competitor_intelligence."""

from __future__ import annotations

from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from app.interfaces.mcp.adapters import (
    CollectInputAdapter,
    CollectOutputAdapter,
    WorkflowRunner,
)
from app.interfaces.mcp.adapters.reliability import run_with_retry
from app.interfaces.mcp.errors import MCPErrorCode
from app.interfaces.mcp.schemas import (
    CollectCompetitorIntelligenceInput,
    CollectCompetitorIntelligenceOutput,
    CompanyContext,
)


COLLECT_TOOL_NAME = "collect_competitor_intelligence"
COLLECT_TOOL_DESCRIPTION = (
    "Collect and normalize competitive intelligence evidence for a given "
    "company, competitor, product, and research objective. Returns structured "
    "evidence with dimensions, sources, confidence, and quality metadata. It "
    "does not generate SWOT analysis, recommendations, or a final report."
)


def register_collect_intelligence_tool(mcp: FastMCP) -> None:
    """Register the collection tool on the provided FastMCP instance."""

    @mcp.tool(name=COLLECT_TOOL_NAME, description=COLLECT_TOOL_DESCRIPTION)
    async def collect_competitor_intelligence(
        input: CollectCompetitorIntelligenceInput,
    ) -> CollectCompetitorIntelligenceOutput:
        """Run collection through the isolated collect_subgraph."""

        try:
            initial_state = CollectInputAdapter().to_initial_state(input)
            internal_state = await run_with_retry(
                lambda: WorkflowRunner().run_collect(initial_state)
            )
            output = CollectOutputAdapter().from_internal_state(
                internal_state,
                max_evidence=input.max_evidence,
            )
            output.collection_id = output.collection_id or str(uuid4())
            return output
        except ValidationError as exc:
            return _error_output(input, MCPErrorCode.COLLECT_VALIDATION_FAILED, str(exc))
        except TimeoutError as exc:
            return _error_output(input, MCPErrorCode.COLLECT_TIMEOUT, str(exc))
        except Exception as exc:
            return _error_output(input, MCPErrorCode.COLLECT_RUNTIME_ERROR, str(exc))

    def _error_output(
        input: CollectCompetitorIntelligenceInput,
        code: MCPErrorCode,
        message: str,
    ) -> CollectCompetitorIntelligenceOutput:
        return CollectCompetitorIntelligenceOutput(
            collection_id=str(uuid4()),
            status="failed",
            error_code=code.value,
            message=message,
            objective=input.objective,
            companies=CompanyContext(
                our_company=input.our_company,
                competitor_company=input.competitor_company,
                product=input.product,
            )
        )
