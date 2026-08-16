"""Unit tests for Insight Quality Gate V1."""

from __future__ import annotations

from app.infrastructure.agents.insight_agent import InsightAgent


class TestBlockRules:
    def test_fact_without_evidence_blocked(self):
        keep, _, _ = InsightAgent._apply_quality_gate(
            "fact", "high", [], [], "desc"
        )
        assert keep is False

    def test_hypothesis_without_evidence_blocked(self):
        keep, _, _ = InsightAgent._apply_quality_gate(
            "hypothesis", "high", [], [], "desc"
        )
        assert keep is False

    def test_observation_without_evidence_not_blocked(self):
        keep, confidence, description = InsightAgent._apply_quality_gate(
            "observation", "medium", [], [], "desc"
        )
        assert keep is True
        assert confidence == "medium"
        assert description == "desc"


class TestWeakHypothesisWarn:
    def test_single_evidence_downgrades_high(self):
        keep, confidence, description = InsightAgent._apply_quality_gate(
            "hypothesis", "high", ["E1"], [], "desc"
        )
        assert keep is True
        assert confidence == "medium"
        assert "有限证据" in description

    def test_single_evidence_downgrades_medium(self):
        keep, confidence, _ = InsightAgent._apply_quality_gate(
            "hypothesis", "medium", ["E1"], [], "desc"
        )
        assert keep is True
        assert confidence == "low"

    def test_low_stays_low(self):
        keep, confidence, _ = InsightAgent._apply_quality_gate(
            "hypothesis", "low", ["E1"], [], "desc"
        )
        assert keep is True
        assert confidence == "low"


class TestPassRules:
    def test_fact_with_evidence_passes(self):
        keep, confidence, description = InsightAgent._apply_quality_gate(
            "fact", "high", ["E1", "E2"], [], "desc"
        )
        assert keep is True
        assert confidence == "high"
        assert description == "desc"

    def test_hypothesis_with_two_evidence_passes(self):
        keep, confidence, description = InsightAgent._apply_quality_gate(
            "hypothesis", "high", ["E1"], ["c1"], "desc"
        )
        assert keep is True
        assert confidence == "high"
        assert description == "desc"
