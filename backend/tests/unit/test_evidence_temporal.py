"""Unit tests for the P0 Evidence Temporal Intelligence changes.

Covers:
  - source published_date passthrough (source wins over LLM date)
  - temporal_level derivation from date
  - temporal + confidence sorting (recent first, historical demoted)
  - aggregate freshness computed from real evaluator scores (no hardcode)
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.application.dto.agent_dto import EvidenceItemDTO
from app.infrastructure.agents.research_agent import ResearchAgent


def _make_item(
    title: str,
    date: str,
    overall_confidence: float,
    freshness_score: float | None = None,
) -> EvidenceItemDTO:
    quality_score: dict = {"overall_confidence": overall_confidence}
    if freshness_score is not None:
        quality_score["freshness_score"] = freshness_score
    return EvidenceItemDTO(
        title=title,
        source="test-source",
        content="test content",
        url=f"https://example.com/{title}",
        date=date,
        quality_score=quality_score,
    )


class TestTemporalLevel:
    def test_recent_aging_stale_historical(self):
        now = datetime.now()
        assert ResearchAgent._compute_temporal_level(
            (now - timedelta(days=100)).strftime("%Y-%m-%d")
        ) == "recent"
        assert ResearchAgent._compute_temporal_level(
            (now - timedelta(days=365 * 2)).strftime("%Y-%m-%d")
        ) == "aging"
        assert ResearchAgent._compute_temporal_level(
            (now - timedelta(days=365 * 4)).strftime("%Y-%m-%d")
        ) == "stale"
        assert ResearchAgent._compute_temporal_level(
            (now - timedelta(days=365 * 6)).strftime("%Y-%m-%d")
        ) == "historical"

    def test_2019_is_historical(self):
        assert ResearchAgent._compute_temporal_level("2019-03-01") == "historical"

    def test_unknown_when_no_date(self):
        assert ResearchAgent._compute_temporal_level("") == "unknown"
        assert ResearchAgent._compute_temporal_level("not-a-date") == "unknown"


class TestDateResolution:
    def test_source_date_wins(self):
        assert (
            ResearchAgent._resolve_evidence_date("2024-06-01", "2025-01-01")
            == "2024-06-01"
        )

    def test_llm_date_fallback(self):
        assert (
            ResearchAgent._resolve_evidence_date("", "2025-01-01")
            == "2025-01-01"
        )

    def test_both_empty(self):
        assert ResearchAgent._resolve_evidence_date("", "") == ""


class TestTemporalSorting:
    def test_2024_2025_prioritized_over_2019(self):
        """Case B: 2024/2025 data must be prioritized into the report."""
        now = datetime.now()
        items = [
            _make_item("2019 市场份额", "2019-03-01", 0.90, 0.20),
            _make_item("2024 行业数据", (now - timedelta(days=365)).strftime("%Y-%m-%d"), 0.70, 0.70),
            _make_item("2025 最新数据", (now - timedelta(days=60)).strftime("%Y-%m-%d"), 0.60, 0.90),
        ]
        sorted_items = ResearchAgent._sort_evidence_by_temporal(items)
        # Recent/aging data must come before the 2019 historical item
        titles = [e.title for e in sorted_items]
        assert titles.index("2025 最新数据") < titles.index("2019 市场份额")
        assert titles.index("2024 行业数据") < titles.index("2019 市场份额")
        assert titles[-1] == "2019 市场份额"

    def test_2019_not_in_top_10(self):
        """Case A: 2019 market-share data must NOT be in the top 10."""
        now = datetime.now()
        items = []
        # 10 recent items
        for i in range(10):
            items.append(
                _make_item(
                    f"recent-{i}",
                    (now - timedelta(days=30 + i)).strftime("%Y-%m-%d"),
                    0.50,
                    0.90,
                )
            )
        # one 2019 historical item
        items.append(_make_item("2019 市场份额", "2019-03-01", 0.95, 0.20))

        sorted_items = ResearchAgent._sort_evidence_by_temporal(items)
        top10_titles = [e.title for e in sorted_items[:10]]
        assert "2019 市场份额" not in top10_titles
        assert sorted_items[-1].title == "2019 市场份额"


class TestAggregateFreshness:
    def test_real_freshness_computed(self):
        items = [
            _make_item("a", "2025-01-01", 0.8, 0.90),
            _make_item("b", "2024-01-01", 0.8, 0.50),
        ]
        # (0.90 + 0.50) / 2 * 100 = 70
        assert ResearchAgent._compute_aggregate_freshness(items) == 70

    def test_unknown_when_no_real_scores(self):
        items = [
            _make_item("a", "2025-01-01", 0.8, None),
            _make_item("b", "2024-01-01", 0.8, None),
        ]
        assert ResearchAgent._compute_aggregate_freshness(items) == "unknown"

    def test_unknown_when_empty(self):
        assert ResearchAgent._compute_aggregate_freshness([]) == "unknown"
