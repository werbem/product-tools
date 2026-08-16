"""Unit tests for Insight Agent temporal consumption (Step 3)."""

from __future__ import annotations

from app.infrastructure.agents.insight_agent import (
    InsightAgent,
    _aggregate_temporal_levels,
)


class TestTemporalResolution:
    def test_recent_cluster(self):
        level = InsightAgent._resolve_insight_temporal(
            ["c1"], [], {"c1": "recent"}, {}
        )
        assert level == "recent"

    def test_mixed_cluster(self):
        level = InsightAgent._resolve_insight_temporal(
            ["c1", "c2"], [],
            {"c1": "recent", "c2": "aging"}, {},
        )
        assert level == "mixed"

    def test_gap_fallback(self):
        level = InsightAgent._resolve_insight_temporal(
            [], ["E1"], {}, {"E1": "recent"}
        )
        assert level == "recent"

    def test_unknown_fallback(self):
        level = InsightAgent._resolve_insight_temporal([], [], {}, {})
        assert level == "unknown"

    def test_cluster_priority_over_gap(self):
        level = InsightAgent._resolve_insight_temporal(
            ["c1"], ["E1"],
            {"c1": "recent"}, {"E1": "historical"},
        )
        assert level == "recent"


class TestTemporalGuard:
    def test_historical_hypothesis_forced_low(self):
        confidence, description = InsightAgent._apply_temporal_guard(
            "hypothesis", "high", "medium", "historical", "desc"
        )
        assert confidence == "low"
        assert "低时效" in description

    def test_stale_observation_downgraded(self):
        confidence, _ = InsightAgent._apply_temporal_guard(
            "observation", "high", "medium", "stale", "desc"
        )
        assert confidence == "medium"

    def test_fact_keeps_confidence(self):
        confidence, description = InsightAgent._apply_temporal_guard(
            "fact", "high", "medium", "historical", "desc"
        )
        assert confidence == "high"
        assert "低时效" in description

    def test_high_impact_appends_risk(self):
        _, description = InsightAgent._apply_temporal_guard(
            "fact", "medium", "high", "historical", "desc"
        )
        assert "影响等级高" in description

    def test_recent_no_guard(self):
        confidence, description = InsightAgent._apply_temporal_guard(
            "hypothesis", "high", "high", "recent", "desc"
        )
        assert confidence == "high"
        assert description == "desc"


class TestBuildTemporalMaps:
    def test_cluster_and_gap_maps(self):
        clusters = [{"cluster_id": "c1", "temporal_level": "recent"}]
        gaps = {
            "gaps": {
                "capability_gaps": [
                    {"evidence_refs": ["E1"], "evidence_temporal_level": "historical"}
                ]
            }
        }
        cluster_map, gap_evidence_map = InsightAgent._build_temporal_maps(clusters, gaps)
        assert cluster_map == {"c1": "recent"}
        assert gap_evidence_map == {"E1": "historical"}


class TestAggregation:
    def test_70_percent(self):
        assert _aggregate_temporal_levels(["recent"] * 8 + ["aging"] * 2) == "recent"
        assert _aggregate_temporal_levels(["recent"] * 5 + ["aging"] * 5) == "mixed"
