"""Unit tests for MCP output governance controls."""

from __future__ import annotations

import unittest

from app.interfaces.mcp.adapters.output_adapter import (
    AnalyzeOutputAdapter,
    CollectOutputAdapter,
)
from app.interfaces.mcp.schemas import MCP_SCHEMA_VERSION


def _collect_state(evidence_items: list[dict]) -> dict:
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
        "evidence_bundle": {"evidence_items": evidence_items},
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
                    "content": "finding",
                    "source": "Tavily",
                    "source_type": "web",
                    "url": "https://example.com",
                    "confidence": "high",
                }
            ]
        },
        "gap_analysis": {
            "positioning": {"our_positioning": "x", "competitor_positioning": "y"},
            "features": {"feature_matrix": [{"feature_name": "f"}]},
            "gaps": {
                "competitive_advantages": [{"description": "advantage"}],
                "capability_gaps": [{"description": "gap"}],
            },
        },
        "strategic_insights": {
            "recommendations": [{"action": "recommendation"}],
            "confidence_labels": {"overall": "high"},
        },
        "review_result": {"passed_for_output": True, "high_issue_count": 0},
        "report_document": {
            "formats": {"markdown": "# Report"},
            "sections": [{"title": "Executive Summary"}],
            "metadata": {"total_word_count": 120},
        },
        "insights": {"summary": "summary"},
    }


class EvidenceOutputControlTest(unittest.TestCase):
    def test_max_evidence_limits_output(self) -> None:
        evidence = [
            {
                "id": f"E{i:03d}",
                "category": "features",
                "content": f"finding {i}",
                "source": "Tavily",
                "source_type": "web",
                "url": f"https://example.com/{i}",
                "confidence": "high" if i % 2 == 0 else "low",
                "quality_score": {
                    "authority_score": 0.5 + (i % 3) * 0.1,
                    "freshness_score": 0.5,
                    "relevance_score": 0.5 + (i % 2) * 0.1,
                    "reliability_score": 0.5,
                    "overall_confidence": 0.5 + (i % 4) * 0.1,
                },
            }
            for i in range(100)
        ]
        output = CollectOutputAdapter().from_internal_state(
            _collect_state(evidence),
            max_evidence=20,
        )
        self.assertEqual(output.coverage.total_evidence, 100)
        self.assertEqual(output.coverage.returned_evidence, 20)
        self.assertEqual(len(output.evidenceItem), 20)


class AnalyzeOutputLevelTest(unittest.TestCase):
    def test_brief_output(self) -> None:
        output = AnalyzeOutputAdapter().from_internal_state(
            _analysis_state(),
            output_level="brief",
        )
        self.assertEqual(output.schema_version, MCP_SCHEMA_VERSION)
        self.assertEqual(output.comparison, {})
        self.assertEqual(output.recommendations, [])
        self.assertEqual(output.report_markdown, "# Report")
        self.assertEqual(output.metadata.word_count, 120)
        self.assertEqual(output.metadata.section_count, 1)
        self.assertIsNone(output.metadata.confidence)

    def test_standard_output(self) -> None:
        output = AnalyzeOutputAdapter().from_internal_state(
            _analysis_state(),
            output_level="standard",
        )
        self.assertTrue(output.comparison)
        self.assertEqual(len(output.recommendations), 1)
        self.assertIsNone(output.metadata.confidence)

    def test_deep_output(self) -> None:
        output = AnalyzeOutputAdapter().from_internal_state(
            _analysis_state(),
            output_level="deep",
        )
        self.assertTrue(output.comparison)
        self.assertEqual(output.metadata.confidence, "high")


if __name__ == "__main__":
    unittest.main()
