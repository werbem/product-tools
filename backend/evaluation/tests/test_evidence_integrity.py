"""Tests for Evidence Referential Integrity Evaluation (V1.2)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.evidence_eval import (
    evidence_reference_integrity,
    insight_traceability_integrity,
    strategy_reference_integrity,
)


def _ev(*ids: str) -> list[dict]:
    return [{"id": i, "title": f"t{i}"} for i in ids]


class TestEvidenceReferenceIntegrity:
    def test_all_refs_valid(self):
        result = evidence_reference_integrity(
            _ev("E001", "E002"),
            [{"evidence_refs": ["E001", "E002"], "cluster_refs": []}],
            [],
        )
        assert result.score == 100.0
        assert result.details["invalid_refs"] == []

    def test_invalid_evidence_ref(self):
        result = evidence_reference_integrity(
            _ev("E001"),
            [{"evidence_refs": ["E001", "E999"], "cluster_refs": []}],
            [],
        )
        assert result.score == 50.0
        assert result.details["invalid_refs"] == ["E999"]


class TestInsightTraceabilityIntegrity:
    def test_insight_no_valid_evidence(self):
        result = insight_traceability_integrity(
            _ev("E001"),
            [{"evidence_refs": ["E999"], "cluster_refs": []}],
        )
        assert result.score < 100
        assert result.details["valid"] == 0


class TestStrategyReferenceIntegrity:
    def test_strategy_references_missing_evidence(self):
        result = strategy_reference_integrity(
            _ev("E001"),
            [{"evidence_refs": ["E999"], "cluster_refs": []}],
        )
        assert result.score < 100
        assert result.details["valid"] == 0


class TestRegression:
    def test_existing_metrics_still_pass(self):
        from evaluation.temporal_eval import evidence_freshness, temporal_compliance
        from evaluation.insight_eval import insight_evidence_coverage
        from evaluation.strategy_eval import strategy_traceability

        evidence = [
            {"id": "E1", "quality_score": {"temporal_level": "recent"}},
            {"id": "E2", "quality_score": {"temporal_level": "recent"}},
        ]
        insights = [{"type": "fact", "evidence_refs": ["E1"], "cluster_refs": []}]
        recs = [{"action": "a", "evidence_refs": ["E1"], "cluster_refs": []}]

        assert evidence_freshness(evidence).score == 100.0
        assert insight_evidence_coverage(insights).score == 100.0
        assert strategy_traceability(recs).score == 100.0
        assert temporal_compliance(evidence, insights, recs, "").score == 100.0
