"""Tests for Production Quality Validation V1."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evaluation.validation.validation import (
    build_summary,
    compare_before_after,
    discover_cases,
    run_validation,
)


def _state(has_qs: bool, updated: str, insights=None, recommendations=None) -> dict:
    evidence = []
    if has_qs:
        evidence = [
            {
                "id": "E1",
                "date": "2026-08-01",
                "quality_score": {"temporal_level": "recent"},
            }
        ]
    return {
        "user_input": {
            "our_company": "飞猪",
            "competitor_company": "美团",
            "product": "酒店",
            "objective": "go_to_market",
        },
        "updated_at": updated,
        "report_document": {"formats": {"markdown": "# report"}},
        "evidence_bundle": {"evidence_items": evidence},
        "insights": {"insights": insights or []},
        "strategic_insights": {"recommendations": recommendations or []},
    }


def _tasks() -> dict:
    return {
        "before1": {"state": _state(False, "2026-07-18T00:00:00")},
        "after1": {"state": _state(True, "2026-08-04T00:00:00")},
    }


class TestDiscoverCases:
    def test_pairs_same_input_before_after(self):
        cases = discover_cases(_tasks())
        assert len(cases) == 1
        assert cases[0]["before_report_id"] == "before1"
        assert cases[0]["after_report_id"] == "after1"


class TestCompareBeforeAfter:
    def test_returns_metric_deltas(self):
        result = compare_before_after(
            _state(False, "2026-07-18"),
            _state(True, "2026-08-04"),
        )
        assert set(result["metrics"]) == {
            "overall_score",
            "temporal_compliance",
            "evidence_integrity",
            "reasoning_quality",
            "strategy_traceability",
        }
        assert "delta" in result["metrics"]["overall_score"]


class TestBuildSummary:
    def test_improved_metrics_and_regressions(self):
        cases = [
            {
                "id": "case_001",
                "evaluation_result": {
                    "metrics": {
                        "overall_score": {"delta": 5},
                        "temporal_compliance": {"delta": 2},
                        "evidence_integrity": {"delta": -10},
                        "reasoning_quality": {"delta": 0},
                        "strategy_traceability": {"delta": 1},
                    },
                    "regressions": [
                        {"type": "metric_regression", "metric": "evidence_integrity", "change": -10, "severity": "high"}
                    ],
                },
            }
        ]
        summary = build_summary(cases)
        assert summary["cases"] == 1
        assert "overall_score" in summary["improved_metrics"]
        assert len(summary["regressions"]) == 1


class TestRunValidation:
    def test_fills_evaluation_result(self):
        tasks = _tasks()
        result = run_validation(tasks)
        assert len(result["cases"]) == 1
        assert result["cases"][0]["evaluation_result"] is not None
        assert "before_after_quality_report" in result
        assert result["summary"]["cases"] == 1
