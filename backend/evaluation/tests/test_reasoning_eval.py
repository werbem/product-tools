"""Tests for Insight Reasoning Quality Evaluation (V1.3)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.reasoning_eval import (
    fact_confidence_consistency,
    hypothesis_evidence_density,
    high_confidence_hypothesis_ratio,
    insight_reasoning_score,
)


class TestFactConfidenceConsistency:
    def test_fact_high_no_evidence(self):
        # Case 1: fact + high confidence + no evidence → score down
        result = fact_confidence_consistency(
            [{"type": "fact", "confidence": "high", "evidence_refs": [], "cluster_refs": []}]
        )
        assert result.score < 100
        assert result.score == 0.0

    def test_fact_with_evidence(self):
        # Case 2: fact + evidence → 100
        result = fact_confidence_consistency(
            [{"type": "fact", "confidence": "high", "evidence_refs": ["E1"], "cluster_refs": []}]
        )
        assert result.score == 100.0


class TestHypothesisEvidenceDensity:
    def test_hypothesis_two_evidence(self):
        # Case 3: hypothesis + 2 evidence → 100
        result = hypothesis_evidence_density(
            [{"type": "hypothesis", "evidence_refs": ["E1", "E2"], "cluster_refs": []}]
        )
        assert result.score == 100.0

    def test_hypothesis_one_evidence(self):
        # Case 4: hypothesis + 1 evidence → down
        result = hypothesis_evidence_density(
            [{"type": "hypothesis", "evidence_refs": ["E1"], "cluster_refs": []}]
        )
        assert result.score == 50.0

    def test_hypothesis_zero_evidence(self):
        result = hypothesis_evidence_density(
            [{"type": "hypothesis", "evidence_refs": [], "cluster_refs": []}]
        )
        assert result.score == 0.0


class TestHighConfidenceHypothesisRatio:
    def test_large_high_confidence_hypothesis(self):
        # Case 5: large high-confidence hypothesis → ratio > 0.6
        insights = [
            {"type": "hypothesis", "confidence": "high", "evidence_refs": ["E1"], "cluster_refs": []}
            for _ in range(3)
        ]
        ratio = high_confidence_hypothesis_ratio(insights)
        assert ratio > 0.6
        assert ratio == 1.0


class TestInsightReasoningScore:
    def test_reasoning_score_composition(self):
        # 2 facts (1 valid high, 1 no evidence), 2 hypotheses (1 weak, 1 strong)
        insights = [
            {"type": "fact", "confidence": "high", "evidence_refs": ["E1"], "cluster_refs": []},
            {"type": "fact", "confidence": "high", "evidence_refs": [], "cluster_refs": []},
            {"type": "hypothesis", "confidence": "high", "evidence_refs": ["E1", "E2"], "cluster_refs": []},
            {"type": "hypothesis", "confidence": "high", "evidence_refs": ["E1"], "cluster_refs": []},
        ]
        result = insight_reasoning_score(insights)
        # fact: 1 valid / 2 = 50; density: (100+50)/2 = 75; ratio=1.0 → penalty=40
        # score = 0.4*50 + 0.4*75 + 0.2*40 = 20 + 30 + 8 = 58
        assert result.score == 58.0
        assert result.details["fact_confidence_consistency"] == 50.0
        assert result.details["hypothesis_density"] == 75.0
        assert result.details["high_confidence_hypothesis_ratio"] == 1.0


class TestRegression:
    def test_existing_metrics_unchanged(self):
        from evaluation.temporal_eval import evidence_freshness, temporal_compliance
        from evaluation.evidence_eval import evidence_reference_integrity

        evidence = [{"id": "E1", "quality_score": {"temporal_level": "recent"}}]
        insights = [{"type": "fact", "confidence": "high", "evidence_refs": ["E1"], "cluster_refs": []}]
        recs = [{"action": "a", "evidence_refs": ["E1"], "cluster_refs": []}]

        assert evidence_freshness(evidence).score == 100.0
        assert evidence_reference_integrity(evidence, insights, recs).score == 100.0
        assert temporal_compliance(evidence, insights, recs, "").score == 100.0
