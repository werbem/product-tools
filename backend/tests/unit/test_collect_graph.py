"""Unit tests for the Phase 2 collect subgraph and output adapter."""

from __future__ import annotations

import unittest

from app.infrastructure.workflow.collect_graph import collect_graph
from app.interfaces.mcp.adapters import (
    CollectInputAdapter,
    CollectOutputAdapter,
)
from app.interfaces.mcp.schemas import CollectCompetitorIntelligenceInput


def _internal_state(
    *,
    evidence_items: list[dict] | None = None,
    sources_attempted: int = 1,
    sources_succeeded: int = 1,
    warnings: list[str] | None = None,
    current_phase: str = "collection_completed",
    errors: list[dict] | None = None,
) -> dict:
    return {
        "task_id": "collection-1",
        "current_phase": current_phase,
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
        "evidence_bundle": {"evidence_items": evidence_items or []},
        "quality_report": {
            "sources_attempted": sources_attempted,
            "sources_succeeded": sources_succeeded,
            "missing_data_warnings": warnings or [],
        },
        "collection_meta": {
            "sources_attempted": sources_attempted,
            "sources_succeeded": sources_succeeded,
            "warnings": warnings or [],
        },
        "errors": errors or [],
    }


class CollectGraphSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def test_normal_input_reaches_collection_complete(self) -> None:
        state = CollectInputAdapter().to_initial_state(
            CollectCompetitorIntelligenceInput(
                our_company="A",
                competitor_company="B",
                product="C",
            )
        )
        internal = await collect_graph.ainvoke(state)
        self.assertEqual(internal["current_phase"], "collection_completed")


class CollectOutputAdapterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CollectOutputAdapter()

    def test_completed_status(self) -> None:
        output = self.adapter.from_internal_state(
            _internal_state(
                evidence_items=[
                    {
                        "id": "E001",
                        "category": "features",
                        "content": "finding",
                        "source": "Tavily",
                        "source_type": "web",
                        "url": "https://example.com",
                        "date": "2026-01-01",
                        "confidence": "high",
                    }
                ]
            )
        )
        self.assertEqual(output.status, "completed")
        self.assertEqual(output.evidenceItem[0].finding_id, "E001")
        self.assertIn("evidenceItem", output.model_dump())

    def test_no_data_status(self) -> None:
        output = self.adapter.from_internal_state(
            _internal_state(
                evidence_items=[],
                sources_attempted=1,
                sources_succeeded=0,
                warnings=["no evidence collected"],
            )
        )
        self.assertEqual(output.status, "no_data")
        self.assertEqual(output.evidenceItem, [])

    def test_partial_status(self) -> None:
        output = self.adapter.from_internal_state(
            _internal_state(
                evidence_items=[
                    {
                        "id": "E001",
                        "category": "features",
                        "content": "finding",
                        "source": "Tavily",
                        "source_type": "web",
                        "url": "https://example.com",
                        "confidence": "medium",
                    }
                ],
                sources_attempted=2,
                sources_succeeded=1,
                warnings=["partial source success: 1/2"],
            )
        )
        self.assertEqual(output.status, "partial")

    def test_failed_status(self) -> None:
        output = self.adapter.from_internal_state(
            _internal_state(current_phase="collection_failed")
        )
        self.assertEqual(output.status, "failed")


if __name__ == "__main__":
    unittest.main()
