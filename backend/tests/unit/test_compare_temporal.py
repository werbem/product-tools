"""Unit tests for Compare Agent temporal consumption (Step 2)."""

from __future__ import annotations

from app.infrastructure.agents.compare_agent import (
    CompareAgent,
    _aggregate_temporal_levels,
    _evidence_sort_key,
    _get_temporal_level,
)
from app.infrastructure.agents.compare_prompt import (
    DifferenceItem,
    LLMCompareOutput,
)


def _item(eid: str, level: str, confidence: str = "medium") -> dict:
    return {
        "id": eid,
        "title": eid,
        "content": "c",
        "date": "",
        "confidence": confidence,
        "quality_score": {"temporal_level": level},
    }


class TestEvidenceSorting:
    def test_recent_sorts_before_historical(self):
        recent = _item("E1", "recent", "estimated")
        historical = _item("E2", "historical", "high")
        assert _evidence_sort_key(recent) < _evidence_sort_key(historical)

    def test_high_confidence_historical_not_before_recent(self):
        recent = _item("E1", "recent", "estimated")
        historical = _item("E2", "historical", "high")
        sorted_items = sorted([historical, recent], key=_evidence_sort_key)
        assert sorted_items[0]["id"] == "E1"

    def test_get_temporal_level(self):
        assert _get_temporal_level(_item("E1", "recent")) == "recent"
        assert _get_temporal_level({"id": "E2"}) == ""


class TestGapTemporalResolution:
    def test_cluster_priority_over_evidence(self):
        level = CompareAgent._resolve_gap_temporal(
            ["c1"], ["E1"],
            cluster_map={"c1": "recent"},
            evidence_map={"E1": "historical"},
        )
        assert level == "recent"

    def test_evidence_aggregation_fallback(self):
        level = CompareAgent._resolve_gap_temporal(
            [], ["E1", "E2"],
            cluster_map={},
            evidence_map={"E1": "recent", "E2": "recent"},
        )
        assert level == "recent"

    def test_historical_only_gap(self):
        # historical-only gap returns "historical" (prompt marks risk)
        level = CompareAgent._resolve_gap_temporal(
            [], ["E1"],
            cluster_map={},
            evidence_map={"E1": "historical"},
        )
        assert level == "historical"

    def test_aggregate_70_percent(self):
        assert _aggregate_temporal_levels(["recent"] * 8 + ["historical"] * 2) == "recent"
        assert _aggregate_temporal_levels(["recent"] * 5 + ["aging"] * 5) == "mixed"


class TestGapOutputTemporal:
    def test_gap_output_has_evidence_temporal_level(self):
        parsed = LLMCompareOutput(
            differences=[],
            capability_gaps=[
                DifferenceItem(
                    dimension="growth",
                    title="cg1",
                    evidence_refs=["E1"],
                    cluster_refs=["c1"],
                )
            ],
            advantages=[],
            disadvantages=[],
            overall_summary="s",
        )
        gap = CompareAgent()._build_gap_analysis(
            parsed,
            [],
            cluster_map={"c1": "recent"},
            evidence_map={"E1": "historical"},
        )
        gaps = gap.gaps["capability_gaps"]
        assert len(gaps) == 1
        assert gaps[0]["evidence_temporal_level"] == "recent"

    def test_gap_without_refs_defaults_unknown(self):
        parsed = LLMCompareOutput(
            differences=[],
            capability_gaps=[
                DifferenceItem(dimension="growth", title="cg1", evidence_refs=[], cluster_refs=[]),
            ],
            advantages=[],
            disadvantages=[],
            overall_summary="s",
        )
        gap = CompareAgent()._build_gap_analysis(parsed, [])
        assert gap.gaps["capability_gaps"][0]["evidence_temporal_level"] == "unknown"
