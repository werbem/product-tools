"""Contract test for collect output -> analyze input compatibility."""

from __future__ import annotations

import unittest

from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionInput,
    CollectCompetitorIntelligenceOutput,
    CompanyContext,
    MCPCoverage,
    MCPEvidenceItem,
    MCPEvidenceSource,
    MCP_SCHEMA_VERSION,
)


def map_collect_output_to_analyze_input(
    collect: CollectCompetitorIntelligenceOutput,
) -> AnalyzeCompetitionInput:
    """Map a collect tool response into the future analyze tool contract.

    Company/product fields stay at the analyze top level. Collection metadata
    and evidence are nested under ``intelligence``.
    """

    return AnalyzeCompetitionInput(
        our_company=collect.companies.our_company,
        competitor_company=collect.companies.competitor_company,
        product=collect.companies.product,
        objective=collect.objective,
        intelligence={
            "schema_version": collect.schema_version,
            "collection_id": collect.collection_id,
            "status": collect.status,
            "dimensions": collect.dimensions,
            "evidence": [item.model_dump() for item in collect.evidenceItem],
            "coverage": collect.coverage.model_dump(),
            "warnings": collect.warnings,
        },
    )


def _sample_collect_output() -> CollectCompetitorIntelligenceOutput:
    return CollectCompetitorIntelligenceOutput(
        collection_id="collection-1",
        status="completed",
        objective="competitive_defense",
        companies=CompanyContext(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
        ),
        dimensions=["features"],
        evidenceItem=[
            MCPEvidenceItem(
                finding_id="E001",
                dimension="features",
                finding="美团酒店拥有更丰富的会员权益",
                source=MCPEvidenceSource(
                    name="Official Website",
                    type="official",
                    url="https://example.com",
                    published_at="2026-01-01",
                ),
                confidence="high",
            )
        ],
        coverage=MCPCoverage(
            total_evidence=1,
            sources_attempted=1,
            sources_succeeded=1,
            by_dimension={"features": 1},
        ),
    )


class CollectToAnalyzeContractTest(unittest.TestCase):
    def test_collect_output_maps_to_analyze_input(self) -> None:
        analyze = map_collect_output_to_analyze_input(_sample_collect_output())

        self.assertEqual(analyze.our_company, "飞猪")
        self.assertEqual(analyze.competitor_company, "美团")
        self.assertEqual(analyze.product, "酒店")
        self.assertEqual(analyze.objective, "competitive_defense")

        intelligence = analyze.intelligence
        self.assertIsNotNone(intelligence)
        self.assertEqual(intelligence["schema_version"], MCP_SCHEMA_VERSION)
        self.assertEqual(intelligence["status"], "completed")
        self.assertEqual(intelligence["evidence"][0]["finding_id"], "E001")
        self.assertEqual(intelligence["coverage"]["total_evidence"], 1)

    def test_no_data_collect_output_is_still_a_valid_analyze_input(self) -> None:
        collect = _sample_collect_output().model_copy(
            update={
                "status": "no_data",
                "evidenceItem": [],
                "coverage": MCPCoverage(),
                "warnings": ["no evidence collected"],
            }
        )
        analyze = map_collect_output_to_analyze_input(collect)
        self.assertEqual(analyze.intelligence["status"], "no_data")
        self.assertEqual(analyze.intelligence["evidence"], [])

    def test_analyze_input_can_omit_intelligence(self) -> None:
        analyze = AnalyzeCompetitionInput(
            our_company="A",
            competitor_company="B",
            product="C",
        )
        self.assertIsNone(analyze.intelligence)


if __name__ == "__main__":
    unittest.main()
