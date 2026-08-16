"""Unit tests for the Evidence Temporal Contract (Step 1).

Covers:
  - EvidenceCluster temporal_level + temporal_distribution
  - 70% dominance aggregation rule
  - backward compatibility (date fallback when temporal_level absent)
  - GapItem.evidence_temporal_level field
"""

from __future__ import annotations

from app.application.dto.agent_dto import GapItem
from app.infrastructure.tools.evidence_clustering import (
    EvidenceClusteringEngine,
    EvidenceCluster,
    _temporal_from_date,
)


def _items(*levels: str) -> list[dict]:
    return [
        {"id": f"e{i}", "title": f"t{i}", "content": "c", "date": "",
         "source_type": "web", "confidence": "medium", "temporal_level": lvl}
        for i, lvl in enumerate(levels)
    ]


class TestTemporalAggregation:
    def test_70_percent_dominance_recent(self):
        # 8 recent + 2 aging => recent is 80% => recent
        items = _items(*(["recent"] * 8 + ["aging"] * 2))
        level, dist = EvidenceClusteringEngine._compute_temporal_aggregation(items)
        assert level == "recent"
        assert dist == {"recent": 8, "aging": 2, "stale": 0, "historical": 0, "unknown": 0}

    def test_no_dominant_is_mixed(self):
        # 5 recent + 5 aging => no tier >= 70% => mixed
        items = _items(*(["recent"] * 5 + ["aging"] * 5))
        level, dist = EvidenceClusteringEngine._compute_temporal_aggregation(items)
        assert level == "mixed"
        assert dist["recent"] == 5
        assert dist["aging"] == 5

    def test_exactly_70_percent_is_dominant(self):
        # 7 historical + 3 unknown => historical is 70% => historical
        items = _items(*(["historical"] * 7 + ["unknown"] * 3))
        level, _ = EvidenceClusteringEngine._compute_temporal_aggregation(items)
        assert level == "historical"


class TestBackwardCompatibility:
    def test_date_fallback_when_temporal_absent(self):
        # No temporal_level, only date -> derive from year
        items = [
            {"id": "e0", "title": "old", "content": "c", "date": "2019-01-01",
             "source_type": "web", "confidence": "medium"},
        ]
        level, dist = EvidenceClusteringEngine._compute_temporal_aggregation(items)
        assert level == "historical"
        assert dist["historical"] == 1

    def test_temporal_from_date(self):
        assert _temporal_from_date("") == "unknown"
        assert _temporal_from_date("not-a-date") == "unknown"
        assert _temporal_from_date("2019-03-01") == "historical"
        assert _temporal_from_date("2023-04-27") == "stale"
        assert _temporal_from_date("2024-06-01") == "aging"


class TestSingleClusterTemporal:
    def test_single_cluster_carries_temporal(self):
        items = _items(*(["recent"] * 8 + ["historical"] * 2))
        cluster = EvidenceClusteringEngine._make_single_cluster(items)
        assert isinstance(cluster, EvidenceCluster)
        assert cluster.temporal_level == "recent"
        assert cluster.temporal_distribution["recent"] == 8
        assert cluster.temporal_distribution["historical"] == 2

    def test_to_dict_includes_temporal(self):
        items = _items("recent", "recent")
        cluster = EvidenceClusteringEngine._make_single_cluster(items)
        d = cluster.to_dict()
        assert "temporal_level" in d
        assert "temporal_distribution" in d


class TestGapItemTemporal:
    def test_gap_item_has_evidence_temporal_level(self):
        g = GapItem(dimension="growth", description="d")
        assert g.evidence_temporal_level == "unknown"

    def test_gap_item_accepts_temporal_level(self):
        g = GapItem(dimension="growth", description="d", evidence_temporal_level="recent")
        assert g.evidence_temporal_level == "recent"
