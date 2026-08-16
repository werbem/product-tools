"""Unit tests for external MCP schemas and Phase 1 adapters.

These tests intentionally do not import the MCP server entrypoint so they can
run in an environment where the optional ``mcp`` runtime is not installed yet.
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from app.interfaces.mcp.adapters import (
    AnalyzeInputAdapter,
    CollectInputAdapter,
    EvidenceStandardizer,
)
from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionInput,
    AnalyzeCompetitionOutput,
    CollectCompetitorIntelligenceInput,
    CollectCompetitorIntelligenceOutput,
    CompanyContext,
    MCPEvidenceItem,
    MCPEvidenceQuality,
    MCPEvidenceSource,
    MCPCoverage,
)


class CollectCompetitorIntelligenceSchemaTest(unittest.TestCase):
    def test_defaults(self) -> None:
        payload = CollectCompetitorIntelligenceInput(
            our_company="字节跳动",
            competitor_company="快手",
            product="抖音",
        )
        self.assertEqual(payload.objective, "product_improvement")
        self.assertEqual(payload.dimensions, [])
        self.assertEqual(payload.max_evidence, 50)

    def test_rejects_empty_company(self) -> None:
        with self.assertRaises(ValidationError):
            CollectCompetitorIntelligenceInput(
                our_company="",
                competitor_company="快手",
                product="抖音",
            )

    def test_output_uses_prd_field_name(self) -> None:
        item = MCPEvidenceItem(
            finding_id="E001",
            source=MCPEvidenceSource(url="https://example.com"),
            quality=MCPEvidenceQuality(overall=0.8),
        )
        output = CollectCompetitorIntelligenceOutput(
            collection_id="collection-1",
            status="completed",
            companies=CompanyContext(
                our_company="字节跳动",
                competitor_company="快手",
                product="抖音",
            ),
            evidenceItem=[item],
            coverage=MCPCoverage(total_evidence=1),
        )
        self.assertEqual(output.evidenceItem[0].finding_id, "E001")
        self.assertEqual(output.model_dump()["evidenceItem"][0]["finding_id"], "E001")


class AnalyzeCompetitionSchemaTest(unittest.TestCase):
    def test_intelligence_is_optional(self) -> None:
        payload = AnalyzeCompetitionInput(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="competitive_defense",
        )
        self.assertIsNone(payload.intelligence)

    def test_output_defaults(self) -> None:
        output = AnalyzeCompetitionOutput(status="completed")
        self.assertEqual(output.comparison, {})
        self.assertEqual(output.report_markdown, "")


class AdapterTest(unittest.TestCase):
    def test_collect_input_adapter(self) -> None:
        payload = CollectCompetitorIntelligenceInput(
            our_company="字节跳动",
            competitor_company="快手",
            product="抖音",
            dimensions=["核心功能对比"],
            source_types=["web"],
        )
        internal = CollectInputAdapter().to_internal_payload(payload)
        self.assertEqual(internal["our_company"], "字节跳动")
        self.assertEqual(internal["dimensions"], ["核心功能对比"])

    def test_analyze_input_adapter(self) -> None:
        payload = AnalyzeCompetitionInput(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            intelligence={"evidenceItem": []},
        )
        internal = AnalyzeInputAdapter().to_internal_payload(payload)
        self.assertEqual(internal["intelligence"], {"evidenceItem": []})

    def test_evidence_standardizer(self) -> None:
        standardizer = EvidenceStandardizer()
        result = standardizer.standardize(
            [
                {
                    "id": "E001",
                    "category": "features",
                    "content": "finding",
                    "source": "Tavily",
                    "source_type": "web",
                    "url": "https://example.com",
                    "date": "2026-01-01",
                    "confidence": "high",
                    "quality_score": {
                        "authority_score": 0.9,
                        "freshness_score": 0.8,
                        "relevance_score": 0.7,
                        "reliability_score": 0.6,
                        "overall_confidence": 0.75,
                    },
                }
            ]
        )
        self.assertEqual(result[0].finding_id, "E001")
        self.assertEqual(result[0].quality.overall, 0.75)


if __name__ == "__main__":
    unittest.main()
