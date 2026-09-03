"""Step 37: Deterministic evidence date enrichment (no LLM)."""

from __future__ import annotations

import asyncio
from datetime import datetime

from app.application.dto.agent_dto import EvidenceItemDTO, ResearchInput
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.tools.evidence_date import (
    enrich_evidence_dates,
    enrich_evidence_item,
    extract_date_from_text,
    extract_date_from_url,
)
from app.infrastructure.tools.research_source import EvidenceItem, SourceResult, SourceType


class TestExtractPatterns:
    def test_url_dashed_ymd(self):
        url = "https://finance.sina.com.cn/tech/2023-04-27/doc-imyhxxxxx.shtml"
        assert extract_date_from_url(url) == "2023-04-27"

    def test_url_compact_yyyymmdd(self):
        url = "https://new.qq.com/rain/a/20260806A01234"
        assert extract_date_from_url(url) == "2026-08-06"

    def test_snippet_chinese_ymd(self):
        text = "据报道，公司于2024年3月15日发布了新版本。"
        assert extract_date_from_text(text) == "2024-03-15"

    def test_iso_datetime_prefix(self):
        assert extract_date_from_text("published 2023-04-27T08:00:00Z") == "2023-04-27"

    def test_slash_and_dot(self):
        assert extract_date_from_text("2023/04/27") == "2023-04-27"
        assert extract_date_from_text("2023.04.27") == "2023-04-27"

    def test_illegal_month_rejected(self):
        assert extract_date_from_text("2023-13-01") is None
        assert extract_date_from_url("https://ex.com/20231301/a") is None

    def test_illegal_day_rejected(self):
        assert extract_date_from_text("2023-02-30") is None

    def test_year_out_of_range_rejected(self):
        assert extract_date_from_text("1989-01-01") is None
        far = datetime.now().year + 2
        assert extract_date_from_text(f"{far}-01-01") is None


class TestEnrichItem:
    def test_existing_date_not_overwritten(self):
        item = EvidenceItemDTO(
            title="keep me",
            source="web",
            url="https://news.example.com/2023-04-27/story",
            date="2020-01-01",
            content="also 2024年3月15日",
        )
        src = enrich_evidence_item(item)
        assert item.date == "2020-01-01"
        assert src == "unchanged"
        assert (item.raw_data or {}).get("date_source") == "unchanged"

    def test_url_fills_empty_date(self):
        item = EvidenceItemDTO(
            title="no date",
            source="sina",
            url="https://finance.sina.com.cn/tech/2023-04-27/doc-imy.shtml",
            date="",
            content="no date here",
        )
        src = enrich_evidence_item(item)
        assert item.date == "2023-04-27"
        assert src == "url"

    def test_snippet_fills_when_no_url_date(self):
        item = EvidenceItemDTO(
            title="plain",
            source="web",
            url="https://example.com/article/plain",
            date="",
            content="发布于2024年3月15日 更新说明",
        )
        src = enrich_evidence_item(item)
        assert item.date == "2024-03-15"
        assert src == "snippet_recent"

    def test_published_date_from_raw_preferred(self):
        item = EvidenceItemDTO(
            title="app",
            source="appstore",
            url="https://apps.apple.com/app/id123",
            date="",
            content="",
            raw_data={"currentVersionReleaseDate": "2025-11-01T00:00:00Z"},
        )
        src = enrich_evidence_item(item)
        assert item.date == "2025-11-01"
        assert src == "published_date"

    def test_no_clues_stays_empty(self):
        item = EvidenceItemDTO(
            title="nothing useful",
            source="web",
            url="https://example.com/docs/intro",
            date="",
            content="generic blurb without a publication marker",
        )
        src = enrich_evidence_item(item)
        assert item.date == ""
        assert src == "none"


class TestResearchIntegration:
    def test_raw_timeout_fallback_url_date_and_temporal(self):
        result = SourceResult(
            items=[
                EvidenceItem(
                    source_type=SourceType.WEB,
                    source_name="Tavily",
                    title="腾讯新闻",
                    url="https://new.qq.com/rain/a/20260806A0ABCD",
                    content="无日期片段",
                    published_date="",
                )
            ],
            source_type=SourceType.WEB,
            source_name="Tavily",
            status="success",
            total_found=1,
        )
        items = ResearchAgent._raw_items_as_evidence(
            result, max_results=5, mark_timeout_fallback=True,
        )
        assert len(items) == 1
        assert items[0].date == "2026-08-06"
        assert (items[0].raw_data or {}).get("extraction_method") == "raw_timeout_fallback"
        assert (items[0].raw_data or {}).get("date_source") == "url"
        level = (items[0].quality_score or {}).get("temporal_level")
        assert level != "unknown"
        assert level in {"recent", "aging", "stale", "historical"}

    def test_build_partial_enriches_url_dates(self):
        agent = ResearchAgent()
        input_data = ResearchInput(
            max_evidence_items=15,
            max_results_per_source=4,
            enable_lightweight_date_enrichment=False,
        )
        agent._partial_input_data = input_data
        agent._partial_all_results = [
            SourceResult(
                items=[
                    EvidenceItem(
                        source_type=SourceType.WEB,
                        source_name="News",
                        title="新浪报道",
                        url="https://finance.sina.com.cn/tech/2023-04-27/doc-imy.shtml",
                        content="内容摘要",
                        published_date="",
                    )
                ],
                source_type=SourceType.WEB,
                source_name="News",
                status="success",
                total_found=1,
            )
        ]
        agent._partial_evidence_items = []
        partial = asyncio.run(agent.build_partial_result())
        assert partial is not None
        items = partial.output.evidence_bundle.evidence_items
        assert items[0].date == "2023-04-27"
        assert (items[0].quality_score or {}).get("temporal_level") != "unknown"

    def test_enrich_batch_preserves_known_dates(self):
        items = [
            EvidenceItemDTO(
                title="a",
                source="s",
                url="https://ex.com/2023-04-27/x",
                date="2021-05-05",
                content="",
            ),
            EvidenceItemDTO(
                title="b",
                source="s",
                url="https://ex.com/plain",
                date="",
                content="",
            ),
        ]
        enrich_evidence_dates(items)
        assert items[0].date == "2021-05-05"
        assert items[1].date == ""

    def test_temporal_unknown_when_no_date(self):
        item = EvidenceItemDTO(
            title="plain",
            source="web",
            url="https://example.com/x",
            date="",
            content="no date",
        )
        ResearchAgent._enrich_evidence_dates([item])
        assert item.date == ""
        assert (item.quality_score or {}).get("temporal_level") == "unknown"
