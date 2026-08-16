"""Unit tests for rule-based evaluation scorers."""

from __future__ import annotations

import unittest

from evaluation.scorer.analysis_scorer import score_analysis
from evaluation.scorer.collection_scorer import score_collection
from evaluation.scorer.mcp_scorer import score_mcp
from evaluation.scorer.scorer import score_case, score_report


class CollectionScorerTest(unittest.TestCase):
    def test_full_collection_score(self) -> None:
        case = {
            "case_id": "case_001",
            "tool": "collect",
            "expected": {"required_dimensions": ["features"]},
        }
        result = {
            "case_id": "case_001",
            "tool": "collect",
            "status": "passed",
            "missing_fields": [],
            "execution_time": 100,
            "output": {
                "coverage": {"by_dimension": {"features": 1}},
                "evidenceItem": [
                    {
                        "finding_id": "E001",
                        "finding": "a finding",
                        "confidence": "high",
                        "quality": {"overall": 0.9},
                        "source": {
                            "name": "Official",
                            "type": "official",
                            "url": "https://example.com",
                        },
                    }
                ],
            },
        }
        metrics = score_collection(case, result)
        self.assertEqual(metrics["coverage_score"], 1.0)
        self.assertEqual(metrics["evidence_quality_score"], 1.0)
        self.assertEqual(metrics["source_quality_score"], 1.0)
        self.assertEqual(metrics["total_score"], 1.0)


class AnalysisScorerTest(unittest.TestCase):
    def test_full_analysis_score(self) -> None:
        case = {"case_id": "case_002", "tool": "analyze", "expected": {}}
        result = {
            "case_id": "case_002",
            "tool": "analyze",
            "status": "passed",
            "missing_fields": [],
            "execution_time": 100,
            "output": {
                "comparison": {"feature_matrix": []},
                "advantages": [{"description": "advantage"}],
                "gaps": [{"description": "gap"}],
                "recommendations": [
                    {
                        "action": "improve",
                        "expected_value": "value",
                        "rationale": "reason",
                    }
                ],
            },
        }
        metrics = score_analysis(case, result)
        self.assertEqual(metrics["completeness_score"], 1.0)
        self.assertEqual(metrics["insight_quality_score"], 1.0)
        self.assertEqual(metrics["recommendation_score"], 1.0)
        self.assertEqual(metrics["total_score"], 1.0)


class MCPMetricsTest(unittest.TestCase):
    def test_fast_passed_response(self) -> None:
        metrics = score_mcp(
            {
                "status": "passed",
                "missing_fields": [],
                "execution_time": 100,
            }
        )
        self.assertEqual(metrics["latency_score"], 1.0)
        self.assertEqual(metrics["failure_rate"], 0.0)
        self.assertEqual(metrics["schema_validation"], 1.0)
        self.assertEqual(metrics["total_score"], 1.0)


class UnifiedScorerTest(unittest.TestCase):
    def test_score_report(self) -> None:
        cases = [
            {
                "case_id": "case_001",
                "tool": "collect",
                "expected": {"required_dimensions": []},
            }
        ]
        results = [
            {
                "case_id": "case_001",
                "tool": "collect",
                "status": "passed",
                "missing_fields": [],
                "execution_time": 100,
                "output": {
                    "coverage": {"by_dimension": {}},
                    "evidenceItem": [],
                },
            }
        ]
        report = score_report(cases, results)
        self.assertIn("average_score", report)
        self.assertEqual(report["failure_cases"], [])


if __name__ == "__main__":
    unittest.main()
