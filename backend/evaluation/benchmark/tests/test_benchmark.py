"""Tests for Analysis Quality Memory & Regression Benchmark V1."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from evaluation.benchmark.benchmark_runner import (
    calculate_quality_trend,
    run_benchmark,
)
from evaluation.benchmark.models import EvaluationSnapshot
from evaluation.benchmark.regression import detect_regression
from evaluation.benchmark.repository import load_snapshots, save_snapshot


def _snap(overall: float, metrics: dict | None = None) -> EvaluationSnapshot:
    return EvaluationSnapshot(
        analysis_version="v1",
        report_id="r1",
        overall_score=overall,
        metrics=metrics or {},
        issues=[],
    )


class TestSnapshotStorage:
    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "history.json"
            save_snapshot(_snap(95, {"reasoning_quality": 100}), path)
            loaded = load_snapshots(path)
            assert len(loaded) == 1
            assert loaded[0]["overall_score"] == 95
            assert loaded[0]["metrics"]["reasoning_quality"] == 100

    def test_load_missing_returns_empty(self):
        with tempfile.TemporaryDirectory() as d:
            assert load_snapshots(Path(d) / "nope.json") == []


class TestRegression:
    def test_overall_regression(self):
        findings = detect_regression(
            {"overall_score": 80, "metrics": {}},
            {"overall_score": 95, "metrics": {}},
        )
        assert any(
            f.type == "regression" and f.metric == "overall_score"
            for f in findings
        )

    def test_metric_regression(self):
        findings = detect_regression(
            {"overall_score": 95, "metrics": {"reasoning_quality": 70}},
            {"overall_score": 95, "metrics": {"reasoning_quality": 100}},
        )
        assert any(
            f.type == "metric_regression" and f.metric == "reasoning_quality"
            for f in findings
        )


class TestBenchmarkRunner:
    def test_10_cases_9_pass(self):
        def fake_evaluate(inp):
            return {
                "overall_score": inp["overall"],
                "metrics": inp["metrics"],
            }

        cases = []
        for i in range(10):
            score = 90 if i < 9 else 50
            cases.append(
                {
                    "id": f"case{i}",
                    "input": {
                        "overall": 90,
                        "metrics": {"reasoning_quality": score},
                    },
                    "expected": {"reasoning_quality": ">=80"},
                }
            )
        result = run_benchmark(cases, evaluate_fn=fake_evaluate)
        assert result.total == 10
        assert result.passed == 9
        assert result.failed == 1
        assert result.regression_detected is False


class TestTrend:
    def test_improving(self):
        t = calculate_quality_trend([_snap(90), _snap(92), _snap(95)])
        assert t.trend == "improving"
        assert t.average_score == 92.33

    def test_declining(self):
        t = calculate_quality_trend([_snap(100), _snap(90), _snap(80)])
        assert t.trend == "declining"
        assert t.average_score == 90.0


class TestRegressionSafety:
    def test_existing_evaluation_still_imports(self):
        from evaluation.quality_evaluator import evaluate

        r = evaluate(
            {
                "evidence_items": [],
                "insights": [],
                "recommendations": [],
                "markdown": "",
            }
        )
        assert r.overall_score is not None
