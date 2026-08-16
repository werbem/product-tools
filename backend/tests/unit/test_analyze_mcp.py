"""Unit and smoke tests for analyze_competition adapter flow."""

from __future__ import annotations

import unittest

from app.interfaces.mcp.adapters import (
    AnalysisRunner,
    AnalyzeInputAdapter,
    AnalyzeOutputAdapter,
    CollectInputAdapter,
    WorkflowRunner,
)
from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionInput,
    CollectCompetitorIntelligenceInput,
    MCP_SCHEMA_VERSION,
)


def _sample_intelligence() -> dict:
    return {
        "schema_version": MCP_SCHEMA_VERSION,
        "collection_id": "collection-1",
        "status": "completed",
        "dimensions": ["features"],
        "evidence": [
            {
                "finding_id": "E001",
                "dimension": "features",
                "finding": "Competitor has a stronger feature set",
                "source": {
                    "name": "Official Website",
                    "type": "official",
                    "url": "https://example.com",
                    "published_at": "2026-01-01",
                },
                "confidence": "high",
                "quality": {
                    "authority": 1.0,
                    "freshness": 0.8,
                    "relevance": 0.9,
                    "reliability": 0.8,
                    "overall": 0.85,
                },
            }
        ],
        "coverage": {
            "total_evidence": 1,
            "sources_attempted": 1,
            "sources_succeeded": 1,
            "by_dimension": {"features": 1},
        },
        "warnings": [],
    }


class AnalyzeAdapterContractTest(unittest.TestCase):
    def test_intelligence_is_converted_to_internal_evidence(self) -> None:
        state = AnalyzeInputAdapter().to_internal_state(
            AnalyzeCompetitionInput(
                our_company="A",
                competitor_company="B",
                product="C",
                intelligence=_sample_intelligence(),
            )
        )
        self.assertEqual(state["validated_input"]["our_company"], "A")
        self.assertEqual(state["research_plan"]["analysis_scope"], ["features"])
        self.assertEqual(len(state["evidence_bundle"]["evidence_items"]), 1)

    def test_output_adapter_maps_failure(self) -> None:
        output = AnalyzeOutputAdapter().from_internal_state(
            {
                "current_phase": "failed",
                "errors": [{"code": "LLM_ERROR"}],
                "evidence_bundle": {"evidence_items": []},
                "gap_analysis": {},
                "strategic_insights": {},
                "review_result": {},
                "report_document": {},
            }
        )
        self.assertEqual(output.status, "failed")
        self.assertEqual(output.schema_version, MCP_SCHEMA_VERSION)

    def test_output_adapter_maps_no_data(self) -> None:
        output = AnalyzeOutputAdapter().from_internal_state(
            {
                "current_phase": "completed",
                "errors": [],
                "evidence_bundle": {"evidence_items": []},
                "gap_analysis": {},
                "strategic_insights": {},
                "review_result": {},
                "report_document": {"formats": {"markdown": "fallback"}},
            }
        )
        self.assertEqual(output.status, "no_data")


class AnalyzeFlowSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_auto_collect_then_analysis(self) -> None:
        collect_state = CollectInputAdapter().to_initial_state(
            CollectCompetitorIntelligenceInput(
                our_company="A",
                competitor_company="B",
                product="C",
            )
        )
        collect_internal = await WorkflowRunner().run_collect(collect_state)
        internal_result = await AnalysisRunner().run(collect_internal)
        output = AnalyzeOutputAdapter().from_internal_state(internal_result)

        self.assertEqual(output.schema_version, MCP_SCHEMA_VERSION)
        self.assertIn(output.status, {"no_data", "partial", "completed"})
        self.assertTrue(output.report_markdown)

    async def test_existing_intelligence_skips_collection(self) -> None:
        state = AnalyzeInputAdapter().to_internal_state(
            AnalyzeCompetitionInput(
                our_company="A",
                competitor_company="B",
                product="C",
                intelligence=_sample_intelligence(),
            )
        )
        internal_result = await AnalysisRunner().run(state)
        output = AnalyzeOutputAdapter().from_internal_state(internal_result)

        self.assertIn(output.status, {"completed", "partial", "no_data"})
        self.assertEqual(output.schema_version, MCP_SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
