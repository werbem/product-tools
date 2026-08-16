"""Unit tests for evaluation report and regression comparison."""

from __future__ import annotations

import unittest

from evaluation.comparison.regression import compare_score_reports
from evaluation.reports.markdown_renderer import render_markdown
from evaluation.reports.report_generator import build_report


def _score_report(
    *,
    average_score: float = 0.9,
    failures: list[str] | None = None,
) -> dict:
    return {
        "average_score": average_score,
        "cases": [
            {
                "case_id": "case_001",
                "total_score": 0.9,
                "metrics": {
                    "coverage_score": 1.0,
                    "evidence_quality_score": 1.0,
                    "source_quality_score": 1.0,
                    "completeness_score": 0.75,
                    "insight_quality_score": 1.0,
                    "recommendation_score": 1.0,
                    "latency": 100,
                    "latency_score": 1.0,
                    "failure_rate": 0.0,
                    "schema_validation": 1.0,
                },
            }
        ],
        "failure_cases": failures or [],
    }


class ReportGeneratorTest(unittest.TestCase):
    def test_build_report_summary_and_metrics(self) -> None:
        report = build_report(_score_report())
        self.assertEqual(report["summary"]["total_cases"], 1)
        self.assertEqual(report["summary"]["passed_cases"], 1)
        self.assertIn("collection_metrics", report["metrics"])
        self.assertIn("analysis_metrics", report["metrics"])
        self.assertIn("mcp_metrics", report["metrics"])

    def test_build_report_counts_failure(self) -> None:
        report = build_report(_score_report(failures=["case_001"]))
        self.assertEqual(report["summary"]["passed_cases"], 0)
        self.assertEqual(report["failures"], ["case_001"])


class MarkdownRenderTest(unittest.TestCase):
    def test_render_contains_required_sections(self) -> None:
        report = build_report(_score_report())
        markdown = render_markdown(report)
        self.assertIn("# Evaluation Report", markdown)
        self.assertIn("## Evaluation Summary", markdown)
        self.assertIn("## Metric Overview", markdown)
        self.assertIn("## Case Detail", markdown)
        self.assertIn("## Failure Cases", markdown)


class RegressionComparisonTest(unittest.TestCase):
    def test_compare_overall_metric_and_case_delta(self) -> None:
        baseline = _score_report(average_score=0.8)
        current = _score_report(average_score=0.9)
        comparison = compare_score_reports(baseline, current)
        self.assertEqual(comparison["overall_score"]["before"], 0.8)
        self.assertEqual(comparison["overall_score"]["after"], 0.9)
        self.assertEqual(comparison["overall_score"]["delta"], 0.1)
        self.assertIn("coverage_score", comparison["metrics"])
        self.assertIn("case_001", comparison["cases"])


if __name__ == "__main__":
    unittest.main()
