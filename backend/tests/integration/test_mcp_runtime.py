"""In-process MCP runtime integration tests.

The local environment does not have the ``mcp`` package installed, so this
test installs a small fake ``mcp.server.fastmcp.FastMCP`` implementation and
imports the real MCP server/tool registration modules through it. Workflow
execution is stubbed to keep these tests focused on the MCP boundary.
"""

from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionInput,
    CollectCompetitorIntelligenceInput,
    MCP_SCHEMA_VERSION,
)


class FakeFastMCP:
    def __init__(self, name: str) -> None:
        self.name = name
        self.tools: dict[str, object] = {}

    def tool(self, name: str | None = None, description: str | None = None):
        def decorator(func):
            self.tools[name or func.__name__] = func
            return func

        return decorator

    async def call_tool(self, name: str, payload):
        return await self.tools[name](payload)


def _fake_mcp_modules() -> dict[str, types.ModuleType]:
    mcp = types.ModuleType("mcp")
    mcp.__path__ = []
    mcp_server = types.ModuleType("mcp.server")
    mcp_server.__path__ = []
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    fastmcp.FastMCP = FakeFastMCP
    return {
        "mcp": mcp,
        "mcp.server": mcp_server,
        "mcp.server.fastmcp": fastmcp,
    }


def _collect_state() -> dict:
    return {
        "task_id": "collection-1",
        "current_phase": "collection_completed",
        "validated_input": {
            "is_valid": True,
            "our_company": "A",
            "competitor_company": "B",
            "product": "C",
            "objective": "product_improvement",
        },
        "user_input": {
            "our_company": "A",
            "competitor_company": "B",
            "product": "C",
            "objective": "product_improvement",
        },
        "research_plan": {"analysis_scope": ["features"]},
        "evidence_bundle": {
            "evidence_items": [
                {
                    "id": "E001",
                    "category": "features",
                    "content": "Competitor has a stronger feature set",
                    "source": "Official Website",
                    "source_type": "official",
                    "url": "https://example.com",
                    "date": "2026-01-01",
                    "confidence": "high",
                }
            ]
        },
        "quality_report": {
            "sources_attempted": 1,
            "sources_succeeded": 1,
            "missing_data_warnings": [],
        },
        "collection_meta": {
            "sources_attempted": 1,
            "sources_succeeded": 1,
            "warnings": [],
        },
        "errors": [],
    }


def _analysis_state() -> dict:
    return {
        "current_phase": "completed",
        "errors": [],
        "evidence_bundle": {
            "evidence_items": [
                {
                    "id": "E001",
                    "category": "features",
                    "content": "Competitor has a stronger feature set",
                    "source": "Official Website",
                    "source_type": "official",
                    "url": "https://example.com",
                    "date": "2026-01-01",
                    "confidence": "high",
                }
            ]
        },
        "gap_analysis": {
            "positioning": {},
            "features": {"feature_matrix": []},
            "gaps": {"competitive_advantages": [], "capability_gaps": []},
        },
        "strategic_insights": {"recommendations": []},
        "review_result": {"passed_for_output": True, "high_issue_count": 0},
        "report_document": {"formats": {"markdown": "# Competitive Analysis"}},
        "insights": {"summary": "summary"},
    }


class MCPRuntimeIntegrationTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._patcher = patch.dict(sys.modules, _fake_mcp_modules())
        self._patcher.start()
        from app.interfaces.mcp.server import create_mcp_server

        self.server = create_mcp_server()
        self.assertEqual(set(self.server.tools), {
            "collect_competitor_intelligence",
            "analyze_competition",
        })

    def tearDown(self) -> None:
        self._patcher.stop()

    async def test_collect_tool_returns_mcp_schema(self) -> None:
        import app.interfaces.mcp.tools.collect_intelligence_tool as collect_module

        with patch.object(
            collect_module.WorkflowRunner,
            "run_collect",
            new=AsyncMock(return_value=_collect_state()),
        ):
            result = await self.server.call_tool(
                "collect_competitor_intelligence",
                CollectCompetitorIntelligenceInput(
                    our_company="A",
                    competitor_company="B",
                    product="C",
                ),
            )

        self.assertEqual(result.schema_version, MCP_SCHEMA_VERSION)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.evidenceItem[0].finding_id, "E001")

    async def test_analyze_without_intelligence_collects_then_analyzes(self) -> None:
        import app.interfaces.mcp.tools.analyze_competition_tool as analyze_module

        with patch.object(
            analyze_module.WorkflowRunner,
            "run_collect",
            new=AsyncMock(return_value=_collect_state()),
        ), patch.object(
            analyze_module.AnalysisRunner,
            "run",
            new=AsyncMock(return_value=_analysis_state()),
        ):
            result = await self.server.call_tool(
                "analyze_competition",
                AnalyzeCompetitionInput(
                    our_company="A",
                    competitor_company="B",
                    product="C",
                ),
            )

        self.assertEqual(result.schema_version, MCP_SCHEMA_VERSION)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.report_markdown, "# Competitive Analysis")

    async def test_analyze_with_intelligence_skips_collect(self) -> None:
        import app.interfaces.mcp.tools.analyze_competition_tool as analyze_module

        with patch.object(
            analyze_module.WorkflowRunner,
            "run_collect",
            new=AsyncMock(side_effect=AssertionError("collect should be skipped")),
        ), patch.object(
            analyze_module.AnalysisRunner,
            "run",
            new=AsyncMock(return_value=_analysis_state()),
        ):
            result = await self.server.call_tool(
                "analyze_competition",
                AnalyzeCompetitionInput(
                    our_company="A",
                    competitor_company="B",
                    product="C",
                    intelligence={"evidence": []},
                ),
            )

        self.assertEqual(result.status, "completed")

    async def test_collect_failure_and_analysis_failure(self) -> None:
        import app.interfaces.mcp.tools.collect_intelligence_tool as collect_module
        import app.interfaces.mcp.tools.analyze_competition_tool as analyze_module

        with patch.object(
            collect_module.WorkflowRunner,
            "run_collect",
            new=AsyncMock(return_value={"current_phase": "collection_failed"}),
        ):
            collect_result = await self.server.call_tool(
                "collect_competitor_intelligence",
                CollectCompetitorIntelligenceInput(
                    our_company="A",
                    competitor_company="B",
                    product="C",
                ),
            )

        with patch.object(
            analyze_module.AnalysisRunner,
            "run",
            new=AsyncMock(side_effect=RuntimeError("analysis boom")),
        ):
            analyze_result = await self.server.call_tool(
                "analyze_competition",
                AnalyzeCompetitionInput(
                    our_company="A",
                    competitor_company="B",
                    product="C",
                    intelligence={"evidence": []},
                ),
            )

        self.assertEqual(collect_result.status, "failed")
        self.assertEqual(analyze_result.status, "failed")


if __name__ == "__main__":
    unittest.main()
