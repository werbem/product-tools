"""Phase 2 Step 3: SimpleQueryService unit tests (fake Tavily + Fake LLM)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.simple_query_service import SimpleQueryService
from app.infrastructure.llm.client import LLMResponse
from app.infrastructure.tools.tavily_tool import TavilyResult


def _intent(**kwargs) -> IntentUnderstandingResult:
    base = dict(
        type="competitive_analysis",
        company="美团",
        competitors=[],
        product="酒店",
        objective="product_improvement",
        confidence=0.8,
        raw_message="美团酒店最近有什么变化",
    )
    base.update(kwargs)
    return IntentUnderstandingResult(**base)  # type: ignore[arg-type]


class TestSimpleQueryService:
    def test_fake_tavily_and_llm_returns_summary_and_sources(self) -> None:
        async def fake_search(**kwargs):
            assert kwargs.get("start_date")
            assert kwargs.get("max_results", 5) <= 5
            return TavilyResult(
                items=[
                    {
                        "title": "美团酒店动态",
                        "url": "https://example.com/a",
                        "content": "2024 年推出会员升级",
                        "published_date": "2024-06-01",
                    },
                    {
                        "title": "过期新闻",
                        "url": "https://example.com/old",
                        "content": "2010 年旧闻",
                        "published_date": "2010-01-01",
                    },
                ],
                status="success",
                total_found=2,
            )

        async def fake_llm(**kwargs):
            return LLMResponse(content="- 会员体系有调整\n\n来源：\n- [美团酒店动态](https://example.com/a)")

        svc = SimpleQueryService(search_fn=fake_search, llm_generate=fake_llm)
        result = asyncio.run(svc.answer(query="美团酒店最近有什么变化", intent=_intent()))
        assert "会员" in result.answer_markdown or "来源" in result.answer_markdown
        assert len(result.sources) == 1
        assert result.sources[0].url == "https://example.com/a"
        assert result.metadata.get("filtered_expired") == 1
        assert result.metadata.get("query_mode") == "information_query"

    def test_empty_search_returns_not_found(self) -> None:
        async def fake_search(**kwargs):
            return TavilyResult(items=[], status="success", total_found=0)

        async def fake_llm(**kwargs):
            raise AssertionError("LLM should not be called when no sources")

        svc = SimpleQueryService(search_fn=fake_search, llm_generate=fake_llm)
        result = asyncio.run(svc.answer(query="某某冷门产品", intent=None))
        assert "未找到" in result.answer_markdown
        assert result.sources == []

    def test_timeout_friendly_no_crash(self) -> None:
        async def slow_search(**kwargs):
            await asyncio.sleep(2.0)
            return TavilyResult(items=[], status="success", total_found=0)

        svc = SimpleQueryService(search_fn=slow_search, timeout_s=0.05)
        result = asyncio.run(svc.answer(query="慢查询", intent=None))
        assert "超时" in result.answer_markdown
        assert result.metadata.get("error") == "timeout"

    def test_search_error_friendly(self) -> None:
        async def err_search(**kwargs):
            return TavilyResult(items=[], status="network_error", error="网络挂了", total_found=0)

        svc = SimpleQueryService(search_fn=err_search, llm_generate=AsyncMock())
        result = asyncio.run(svc.answer(query="x", intent=None))
        assert "检索" in result.answer_markdown or "失败" in result.answer_markdown or "网络" in result.answer_markdown
