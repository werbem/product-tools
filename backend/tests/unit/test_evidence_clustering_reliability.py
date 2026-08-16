"""Unit tests for Evidence Clustering reliability fix (_build_clusters)."""

from __future__ import annotations

from app.infrastructure.tools.evidence_clustering import EvidenceClusteringEngine


def _evidence_items() -> list[dict]:
    return [
        {"id": "E001", "title": "t1", "content": "c", "source_type": "web",
         "confidence": "high", "date": "2026-07-01", "temporal_level": "recent"},
        {"id": "E002", "title": "t2", "content": "c", "source_type": "app_store",
         "confidence": "high", "date": "2026-06-01", "temporal_level": "recent"},
        {"id": "E003", "title": "t3", "content": "c", "source_type": "news",
         "confidence": "medium", "date": "2024-01-01", "temporal_level": "aging"},
        {"id": "E004", "title": "t4", "content": "c", "source_type": "web",
         "confidence": "low", "date": "2019-01-01", "temporal_level": "historical"},
        {"id": "E005", "title": "t5", "content": "c", "source_type": "web",
         "confidence": "high", "date": "2026-05-01", "temporal_level": "recent"},
    ]


class TestBuildClusters:
    def test_two_clusters_with_separate_temporal(self):
        clusters_data = [
            {"topic": "近期功能", "evidence_refs": ["E001", "E002", "E005"],
             "summary": "近期", "confidence": 0.9},
            {"topic": "历史背景", "evidence_refs": ["E003", "E004"],
             "summary": "历史", "confidence": 0.6},
        ]
        clusters = EvidenceClusteringEngine._build_clusters(
            clusters_data, _evidence_items()
        )
        assert len(clusters) == 2

        c1, c2 = clusters
        # 3 recent -> 100% -> recent
        assert c1.temporal_level == "recent"
        assert c1.temporal_distribution == {
            "recent": 3, "aging": 0, "stale": 0, "historical": 0, "unknown": 0,
        }
        # 1 aging + 1 historical -> no 70% -> mixed
        assert c2.temporal_level == "mixed"
        assert c2.temporal_distribution["aging"] == 1
        assert c2.temporal_distribution["historical"] == 1

    def test_evidence_refs_resolve_to_actual_ids(self):
        # LLM returns positional "e1, e2" per prompt instruction
        clusters_data = [
            {"topic": "a", "evidence_refs": ["e1", "e2"], "summary": "", "confidence": 0.8},
        ]
        clusters = EvidenceClusteringEngine._build_clusters(
            clusters_data, _evidence_items()
        )
        assert len(clusters) == 1
        assert clusters[0].evidence_refs == ["E001", "E002"]

    def test_unresolvable_cluster_skipped(self):
        clusters_data = [
            {"topic": "bad", "evidence_refs": ["E999"], "summary": "", "confidence": 0.5},
        ]
        clusters = EvidenceClusteringEngine._build_clusters(
            clusters_data, _evidence_items()
        )
        assert clusters == []

    def test_empty_clusters_data_returns_empty(self):
        assert EvidenceClusteringEngine._build_clusters([], _evidence_items()) == []

    def test_source_diversity_and_confidence(self):
        clusters_data = [
            {"topic": "a", "evidence_refs": ["E001", "E002"],
             "summary": "", "confidence": 0.7},
        ]
        clusters = EvidenceClusteringEngine._build_clusters(
            clusters_data, _evidence_items()
        )
        c = clusters[0]
        assert c.confidence == 0.7
        assert c.source_diversity == {"web": 1, "app_store": 1}
        assert c.evidence_count == 2


class TestFallbackStillComputesTemporal:
    def test_single_cluster_fallback_computes_temporal(self):
        items = _evidence_items()
        cluster = EvidenceClusteringEngine._make_single_cluster(items)
        # 3 recent + 1 aging + 1 historical = 5 items; 3/5 = 60% < 70% => mixed
        assert cluster.temporal_level == "mixed"
        assert cluster.temporal_distribution["recent"] == 3
        assert cluster.temporal_distribution["historical"] == 1
