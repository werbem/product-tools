"""Tests for the Analysis Quality Evaluation Layer V1."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.insight_eval import (
    insight_evidence_coverage,
    insight_quality_distribution,
)
from evaluation.strategy_eval import strategy_traceability
from evaluation.temporal_eval import evidence_freshness, temporal_compliance
from evaluation.quality_evaluator import evaluate, normalize_report_input


def _evidence() -> list[dict]:
    return [
        {"id": "E1", "date": "2026-08-01", "quality_score": {"temporal_level": "recent"}},
        {"id": "E2", "date": "2026-07-01", "quality_score": {"temporal_level": "recent"}},
        {"id": "E3", "date": "2025-01-01", "quality_score": {"temporal_level": "aging"}},
        {"id": "E4", "date": "2019-01-01", "quality_score": {"temporal_level": "historical"}},
    ]


def _insights() -> list[dict]:
    return [
        {"type": "fact", "evidence_refs": ["E1"], "cluster_refs": [], "confidence": "high"},
        {"type": "fact", "evidence_refs": [], "cluster_refs": [], "confidence": "medium"},
        {"type": "hypothesis", "evidence_refs": ["E1"], "cluster_refs": [], "confidence": "high"},
        {"type": "hypothesis", "evidence_refs": [], "cluster_refs": [], "confidence": "medium"},
    ]


def _recommendations() -> list[dict]:
    return [
        {"action": "a1", "evidence_refs": ["E1"], "cluster_refs": []},
        {"action": "a2", "evidence_refs": [], "cluster_refs": []},
    ]


class TestInsightMetrics:
    def test_evidence_coverage(self):
        result = insight_evidence_coverage(_insights())
        assert result.score == 50.0
        assert result.details["supported"] == 2
        assert result.details["unsupported"] == 2

    def test_quality_distribution(self):
        result = insight_quality_distribution(_insights())
        assert result.details["fact_count"] == 2
        assert result.details["hypothesis_count"] == 2
        assert result.details["confidence_distribution"]["high"] == 2
        assert result.details["high_confidence_hypothesis_ratio"] == 0.25


class TestStrategyMetrics:
    def test_traceability(self):
        result = strategy_traceability(_recommendations())
        assert result.score == 50.0
        assert result.details["traceable"] == 1
        assert result.details["untraceable"] == 1


class TestTemporalMetrics:
    def test_freshness(self):
        result = evidence_freshness(_evidence())
        # (2*1.0 + 1*0.75 + 1*0.1) / 4 = 2.85/4 = 71.25
        assert result.score == 71.25
        assert result.details["distribution"]["recent"] == 2
        assert result.details["distribution"]["historical"] == 1

    def test_temporal_compliance_no_historical_ref(self):
        result = temporal_compliance(
            _evidence(), _insights(), _recommendations(), ""
        )
        assert result.score == 100.0
        assert result.details["structured_historical_reference_count"] == 0
        assert result.details["markdown_historical_reference_count"] == 0

    def test_temporal_compliance_bad_usage(self):
        recs = [
            {"action": "a1", "evidence_refs": ["E4"], "cluster_refs": []},
        ]
        result = temporal_compliance(_evidence(), [], recs, "")
        # structured_score=0, markdown_score=100 → 50
        assert result.score == 50.0
        assert result.details["structured_bad_usage_count"] == 1
        assert result.details["structured_score"] == 0.0
        assert result.details["markdown_score"] == 100.0


class TestTemporalComplianceV11:
    def test_structured_violation_only(self):
        # Case 1: historical evidence referenced by a fact insight
        evidence = [
            {"id": "E4", "date": "2019-01-01", "quality_score": {"temporal_level": "historical"}},
        ]
        insights = [
            {"type": "fact", "evidence_refs": ["E4"], "cluster_refs": [], "confidence": "high"},
        ]
        result = temporal_compliance(evidence, insights, [], "")
        assert result.details["structured_score"] < 100
        assert result.details["markdown_score"] == 100.0

    def test_markdown_violation_only(self):
        # Case 2: historical evidence cited near current-state keywords
        evidence = [
            {"id": "E017", "date": "2018-12-06", "quality_score": {"temporal_level": "historical"}},
        ]
        markdown = "美团在低星酒店市场占据强势地位[E017]"
        result = temporal_compliance(evidence, [], [], markdown)
        assert result.details["markdown_score"] < 100
        assert result.details["markdown_bad_usage_count"] == 1

    def test_before_report_regression(self):
        # Case 3: 7 markdown historical misuse → compliance < 100
        evidence = [
            {"id": "E4", "date": "2019-01-01", "quality_score": {"temporal_level": "historical"}},
        ]
        markdown = "美团占据强势地位[E4]\n" * 7
        result = temporal_compliance(evidence, [], [], markdown)
        assert result.score < 100
        assert result.details["markdown_bad_usage_count"] == 7

    def test_after_report_no_misuse(self):
        # Case 4: no historical misuse → compliance = 100
        evidence = [
            {"id": "E1", "date": "2026-08-01", "quality_score": {"temporal_level": "recent"}},
        ]
        markdown = "美团近期推出新功能[E1]"
        result = temporal_compliance(evidence, [], [], markdown)
        assert result.score == 100.0

    def test_no_markdown(self):
        # Case 5: no markdown field → no error, markdown_score = 100
        result = temporal_compliance(_evidence(), [], [], "")
        assert result.details["markdown_score"] == 100.0


class TestEvaluator:
    def test_normalize_report_input_from_tasks_shape(self):
        data = {
            "evidence_bundle": {"evidence_items": _evidence()},
            "insights": {"insights": _insights()},
            "strategic_insights": {"recommendations": _recommendations()},
            "report_document": {"formats": {"markdown": "# report"}},
        }
        normalized = normalize_report_input(data)
        assert len(normalized["evidence_items"]) == 4
        assert len(normalized["insights"]) == 4
        assert len(normalized["recommendations"]) == 2
        assert normalized["markdown"] == "# report"

    def test_evaluate_end_to_end(self):
        data = {
            "evidence_bundle": {"evidence_items": _evidence()},
            "insights": {"insights": _insights()},
            "strategic_insights": {"recommendations": _recommendations()},
            "markdown": "# report",
        }
        result = evaluate(normalize_report_input(data))
        # 6 scored metrics: temporal(100) + coverage(50) + traceability(50)
        # + freshness(71.25) + evidence_integrity(66.67) + reasoning_quality(64)
        assert result.overall_score == round((100 + 50 + 50 + 71.25 + 66.67 + 64) / 6, 2)
        assert "temporal_compliance" in result.metrics
        assert "insight_evidence_coverage" in result.metrics
        assert "strategy_traceability" in result.metrics
        assert "freshness" in result.metrics
        assert "evidence_integrity" in result.metrics
        assert "reasoning_quality" in result.metrics
