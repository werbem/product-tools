"""Step 42: evidence age window + lightweight page_meta enrichment."""

from __future__ import annotations

import asyncio
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.application.dto.agent_dto import EvidenceItemDTO, ResearchInput
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.tools.evidence_date import enrich_evidence_item
from app.infrastructure.tools.evidence_freshness import (
    apply_evidence_age_window,
    cutoff_iso,
    evidence_cutoff_date,
    enrich_missing_dates_from_page_meta,
    extract_published_date_from_html,
    freshness_query_hint,
)
from app.infrastructure.tools.sources.tavily_source import TavilySource
from app.infrastructure.tools.tavily_tool import TavilyResult
from app.infrastructure.workflow.analysis_mode import get_mode_config


FAKE_HTML = """
<html><head>
<meta property="article:published_time" content="2024-06-15T08:00:00Z" />
</head><body><p>hello</p></body></html>
"""


def _item(**kwargs) -> EvidenceItemDTO:
    defaults = dict(
        id="E001",
        title="t",
        source="web",
        source_type="web",
        url="https://example.com/news/2024/article-1",
        date="",
        content="c",
        confidence="medium",
        category="features",
        raw_data={},
        quality_score={},
    )
    defaults.update(kwargs)
    return EvidenceItemDTO(**defaults)


class TestAnalysisModeFreshnessConfig:
    def test_fast_and_full_enable_window(self):
        for mode in ("fast", "full"):
            cfg = get_mode_config(mode)
            assert cfg.evidence_max_age_months == 48
            assert cfg.max_undated_evidence_items == 5
            assert cfg.enable_lightweight_date_enrichment is True
            assert cfg.date_enrichment_timeout_s == 2.5
            assert cfg.date_enrichment_max_urls == 8


class TestAgeWindow:
    def test_cutoff_and_hint(self):
        today = date(2026, 9, 2)
        assert evidence_cutoff_date(48, today=today) == date(2022, 9, 2)
        assert cutoff_iso(48, today=today) == "2022-09-02"
        assert "2022" in freshness_query_hint(48, today=today)

    def test_expired_dated_excluded(self):
        items = [
            _item(id="E001", date="2011-05-01", url="https://a.com/1"),
            _item(id="E002", date="2024-01-01", url="https://a.com/2"),
        ]
        main, meta = apply_evidence_age_window(
            items, max_age_months=48, max_undated_evidence_items=5, today=date(2026, 9, 2),
        )
        assert len(main) == 1
        assert main[0].date == "2024-01-01"
        assert meta["filtered_expired_count"] == 1
        assert meta["evidence_cutoff_date"] == "2022-09-02"

    def test_undated_capped_at_five(self):
        items = [
            _item(id=f"E{i:03d}", date="", url=f"https://a.com/{i}")
            for i in range(1, 9)
        ]
        main, meta = apply_evidence_age_window(
            items, max_age_months=48, max_undated_evidence_items=5, today=date(2026, 9, 2),
        )
        assert len(main) == 5
        assert meta["undated_kept_count"] == 5
        assert meta["undated_dropped_count"] == 3

    def test_event_date_expired_excluded(self):
        items = [
            _item(
                id="E001",
                date="2011-03-01",
                url="https://corp.com/abouts",
                content="2011 年大事记",
                raw_data={"date_semantic": "event_date", "date_source": "timeline_event_recent"},
            ),
            _item(id="E002", date="2025-01-01", url="https://a.com/ok"),
        ]
        main, meta = apply_evidence_age_window(
            items, max_age_months=48, max_undated_evidence_items=5, today=date(2026, 9, 2),
        )
        assert [e.id for e in main] == ["E002"]
        assert meta["filtered_expired_count"] == 1


class TestPageMetaEnrichment:
    def test_extract_article_published_time(self):
        assert extract_published_date_from_html(FAKE_HTML) == "2024-06-15"

    def test_enrich_from_fake_html_fixture(self):
        item = _item(date="", url="https://news.example.com/2024/story")
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "text/html"}

        async def fake_aiter_bytes():
            yield FAKE_HTML.encode("utf-8")

        mock_resp.aiter_bytes = fake_aiter_bytes
        mock_stream = MagicMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_stream.__aexit__ = AsyncMock(return_value=None)
        mock_client = MagicMock()
        mock_client.stream = MagicMock(return_value=mock_stream)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch(
            "app.infrastructure.tools.evidence_freshness.httpx.AsyncClient",
            return_value=mock_client,
        ):
            stats = asyncio.run(
                enrich_missing_dates_from_page_meta(
                    [item], enabled=True, max_urls=8, timeout_s=2.5, concurrency=3,
                )
            )
        assert stats["succeeded"] == 1
        assert item.date == "2024-06-15"
        assert item.raw_data.get("date_source") == "page_meta"
        assert item.raw_data.get("date_semantic") == "publish_date"

        # After enrich, window may keep it
        main, meta = apply_evidence_age_window(
            [item], max_age_months=48, today=date(2026, 9, 2),
        )
        assert len(main) == 1
        assert meta["filtered_expired_count"] == 0

    def test_enrich_failure_keeps_unknown(self):
        item = _item(date="", url="https://news.example.com/2024/x")
        with patch(
            "app.infrastructure.tools.evidence_freshness.httpx.AsyncClient",
            side_effect=TimeoutError("boom"),
        ):
            stats = asyncio.run(
                enrich_missing_dates_from_page_meta(
                    [item], enabled=True, max_urls=8, timeout_s=0.1, concurrency=1,
                )
            )
        assert stats["failed"] >= 1
        assert not item.date


class TestTavilyTimeParams:
    def test_tavily_source_passes_start_date(self):
        captured = {}

        async def fake_search(**kwargs):
            captured.update(kwargs)
            return TavilyResult(items=[], status="success", total_found=0)

        src = TavilySource()
        with patch(
            "app.infrastructure.tools.sources.tavily_source.tavily_search",
            side_effect=fake_search,
        ):
            asyncio.run(
                src.search(
                    "飞猪 竞品",
                    context={
                        "task_id": "t1",
                        "max_results_per_source": 3,
                        "evidence_start_date": "2022-09-02",
                        "freshness_query_hint": "优先2022年至今的公开信息",
                    },
                )
            )
        assert captured.get("start_date") == "2022-09-02"
        assert "优先2022年至今" in (captured.get("query") or "")


class TestResearchPipeline:
    def test_pipeline_filters_expired_and_caps_undated(self):
        agent = ResearchAgent()
        input_data = ResearchInput(
            our_company="A",
            competitor_company="B",
            product="P",
            evidence_max_age_months=48,
            max_undated_evidence_items=5,
            enable_lightweight_date_enrichment=False,
            max_evidence_items=20,
        )
        items = [
            _item(id="E001", date="2010-01-01", url="https://a.com/old"),
            _item(
                id="E002",
                date="2011-01-01",
                url="https://a.com/abouts",
                content="大事记 2011",
                raw_data={"date_semantic": "event_date"},
            ),
            *[_item(id=f"E{i:03d}", date="", url=f"https://a.com/u{i}") for i in range(3, 12)],
            _item(id="E012", date="2025-02-01", url="https://a.com/new"),
        ]
        out = asyncio.run(agent._apply_date_and_freshness_pipeline(items, input_data))
        dates = [e.date for e in out]
        assert "2010-01-01" not in dates
        assert "2011-01-01" not in dates
        assert "2025-02-01" in dates
        undated = [e for e in out if not e.date]
        assert len(undated) <= 5
        meta = agent._last_freshness_meta
        assert meta["filtered_expired_count"] >= 2
        assert meta["evidence_cutoff_date"]

    def test_multi_date_still_picks_recent_pr41(self):
        item = SimpleNamespace(
            date="",
            url="https://corp.example.com/abouts ",
            title="公司大事记",
            content="2011年成立；2020年上市；2024-07-02 发布新品",
            raw_data={},
            quality_score={},
        )
        enrich_evidence_item(item)
        assert item.date == "2024-07-02"
        assert item.raw_data.get("date_semantic") == "event_date"


class TestCompareInputNoExpired:
    def test_compress_skips_what_research_already_filtered(self):
        from app.infrastructure.agents.agent_io_compact import compress_evidence_items

        items = [
            _item(id="E001", date="2024-01-01", content="ok"),
            _item(id="E002", date="", content="undated ok"),
        ]
        compressed = compress_evidence_items(items, cap=8)
        assert all(c["id"] in ("E001", "E002") for c in compressed)
        assert not any(c.get("date") == "2011-01-01" for c in compressed)
