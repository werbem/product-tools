"""Unit tests for Strategy Agent temporal inheritance (Step 4)."""

from __future__ import annotations

from app.infrastructure.agents.strategy_agent import (
    StrategyAgent,
    _aggregate_temporal_levels,
)


class TestTemporalInheritance:
    def test_build_insight_temporal_maps(self):
        insights = [
            {"evidence_temporal_level": "recent", "cluster_refs": ["c1"], "evidence_refs": ["E1"]},
            {"evidence_temporal_level": "historical", "cluster_refs": ["c2"], "evidence_refs": ["E2"]},
        ]
        cluster_map, evidence_map = StrategyAgent._build_insight_temporal_maps(insights)
        assert cluster_map == {"c1": "recent", "c2": "historical"}
        assert evidence_map == {"E1": "recent", "E2": "historical"}

    def test_cluster_priority(self):
        level = StrategyAgent._resolve_recommendation_temporal(
            ["c1"], ["E1"],
            {"c1": "recent"}, {"E1": "historical"},
        )
        assert level == "recent"

    def test_evidence_fallback(self):
        level = StrategyAgent._resolve_recommendation_temporal(
            [], ["E1"], {}, {"E1": "recent"}
        )
        assert level == "recent"

    def test_unknown_fallback(self):
        level = StrategyAgent._resolve_recommendation_temporal([], [], {}, {})
        assert level == "unknown"


class TestTemporalGuard:
    def test_historical_appends_hint(self):
        rationale = StrategyAgent._apply_temporal_guard("做A", "historical")
        assert "低时效" in rationale
        assert rationale.startswith("做A ")

    def test_stale_appends_hint(self):
        rationale = StrategyAgent._apply_temporal_guard("做B", "stale")
        assert "低时效" in rationale

    def test_recent_no_hint(self):
        assert StrategyAgent._apply_temporal_guard("做C", "recent") == "做C"

    def test_empty_rationale(self):
        rationale = StrategyAgent._apply_temporal_guard("", "historical")
        assert rationale == "该建议主要基于低时效数据，需要近期数据验证"


class TestAggregation:
    def test_70_percent(self):
        assert _aggregate_temporal_levels(["recent"] * 8 + ["historical"] * 2) == "recent"
        assert _aggregate_temporal_levels(["recent"] * 5 + ["aging"] * 5) == "mixed"
