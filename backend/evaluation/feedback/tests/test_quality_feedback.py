"""Tests for Analysis Quality Feedback Loop V1."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evaluation.feedback.diagnosis_rules import diagnose
from evaluation.feedback.improvement_rules import build_generation_constraints
from evaluation.feedback.quality_feedback import evaluate_feedback


def _result(overall: float, metrics: dict) -> dict:
    return {"overall_score": overall, "metrics": metrics}


class TestOverallHealth:
    def test_good_no_issues(self):
        fb = evaluate_feedback(
            _result(
                95,
                {
                    "temporal_compliance": {"score": 100},
                    "evidence_integrity": {"score": 100},
                    "reasoning_quality": {"score": 100},
                },
            )
        )
        assert fb.overall_health == "good"
        assert fb.issues == []

    def test_warning_boundary(self):
        assert evaluate_feedback(_result(70, {})).overall_health == "warning"
        assert evaluate_feedback(_result(89.9, {})).overall_health == "warning"

    def test_poor(self):
        assert evaluate_feedback(_result(69, {})).overall_health == "poor"


class TestDiagnosisRules:
    def test_temporal_low(self):
        fb = evaluate_feedback(
            _result(80, {"temporal_compliance": {"score": 60}})
        )
        rules = [c["rule"] for c in fb.generation_constraints]
        assert any("historical" in r.lower() for r in rules)
        assert any(i["metric"] == "temporal_compliance" for i in fb.issues)

    def test_reasoning_low(self):
        fb = evaluate_feedback(
            _result(80, {"reasoning_quality": {"score": 60}})
        )
        rules = [c["rule"] for c in fb.generation_constraints]
        assert any("hypothesis" in r for r in rules)
        assert any("evidence_count" in r for r in rules)

    def test_multiple_metrics_sorted_by_severity(self):
        issues = diagnose(
            {
                "reasoning_quality": {"score": 60},  # medium
                "temporal_compliance": {"score": 60},  # high
            }
        )
        assert issues[0]["metric"] == "temporal_compliance"
        assert issues[0]["severity"] == "high"


class TestImprovementRules:
    def test_semantic_low_generates_recommendation_constraint(self):
        fb = evaluate_feedback(
            _result(80, {"semantic_reasoning": {"score": 50}})
        )
        assert any(
            c["rule"] == "recommendation必须区分fact和hypothesis"
            for c in fb.generation_constraints
        )

    def test_constraints_are_deduplicated(self):
        issues = diagnose(
            {"temporal_compliance": {"score": 60}}
        )
        constraints = build_generation_constraints(issues * 2)
        assert len(constraints) == 1


class TestRegression:
    def test_evaluation_layer_still_imports(self):
        from evaluation.quality_evaluator import evaluate

        result = evaluate(
            {
                "evidence_items": [],
                "insights": [],
                "recommendations": [],
                "markdown": "",
            }
        )
        assert result.overall_score is not None
