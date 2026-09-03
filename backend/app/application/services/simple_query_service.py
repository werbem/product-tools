"""Lightweight information query — search + short LLM summary (Phase 2 Step 3)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.infrastructure.llm.client import LLMClient, LLMResponse, llm_client
from app.infrastructure.tools.evidence_freshness import cutoff_iso, freshness_query_hint
from app.infrastructure.tools.tavily_tool import TavilyResult, tavily_search

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 55.0
_MAX_RESULTS = 5
_EVIDENCE_MAX_AGE_MONTHS = 48

_SYSTEM_PROMPT = """你是竞品分析助手的轻量信息查询模块。
根据检索到的公开资料作答，输出简洁 Markdown：
- 用 4～8 条短 bullet，或一段 300～600 字以内摘要
- 只依据给定来源；不要编造链接或事实
- 不要输出竞品分析报告结构（禁止十三章/SWOT/完整对比矩阵）
- 若来源无明确日期，不要断言「最新/近期」
- 信息不足时明确写「未找到足够公开信息」
- 项目记忆与企业知识笔记仅作内部背景，不可伪造成公开来源；引用笔记时标明「内部笔记」
"""

class QuerySource(BaseModel):
    title: str = ""
    url: str = ""
    snippet: str = ""
    published_date: str = ""


class SimpleQueryResult(BaseModel):
    answer_markdown: str
    sources: list[QuerySource] = Field(default_factory=list)
    confidence: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)


TavilySearchFn = Callable[..., Awaitable[TavilyResult]]
LlmGenerateFn = Callable[..., Awaitable[LLMResponse]]


class SimpleQueryService:
    def __init__(
        self,
        *,
        search_fn: TavilySearchFn | None = None,
        llm: LLMClient | None = None,
        llm_generate: LlmGenerateFn | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_results: int = _MAX_RESULTS,
        max_age_months: int = _EVIDENCE_MAX_AGE_MONTHS,
    ) -> None:
        self._search = search_fn or tavily_search
        self._llm = llm or llm_client
        self._llm_generate = llm_generate
        self._timeout_s = float(timeout_s)
        self._max_results = max(1, min(int(max_results), 8))
        self._max_age_months = int(max_age_months)

    async def answer(
        self,
        *,
        query: str,
        intent: IntentUnderstandingResult | None = None,
        conversation_id: str | None = None,
        project_memory_block: str | None = None,
        knowledge_notes_block: str | None = None,
    ) -> SimpleQueryResult:
        started = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._answer_inner(
                    query=query,
                    intent=intent,
                    conversation_id=conversation_id,
                    project_memory_block=project_memory_block,
                    knowledge_notes_block=knowledge_notes_block,
                ),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return SimpleQueryResult(
                answer_markdown=(
                    "查询超时，未能在限定时间内完成检索与摘要。"
                    "请稍后重试，或改用「竞品分析报告」/「帮我收集…」获取更完整结果。"
                ),
                sources=[],
                confidence=0.1,
                metadata={
                    "query_mode": "information_query",
                    "error": "timeout",
                    "elapsed_ms": elapsed_ms,
                    "conversation_id": conversation_id,
                },
            )
        except Exception as exc:
            logger.exception("simple_query failed: %s", exc)
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return SimpleQueryResult(
                answer_markdown=(
                    "查询暂时失败，请稍后重试。"
                    "如需完整分析可改写为「请做竞品分析报告…」。"
                ),
                sources=[],
                confidence=0.1,
                metadata={
                    "query_mode": "information_query",
                    "error": type(exc).__name__,
                    "elapsed_ms": elapsed_ms,
                    "conversation_id": conversation_id,
                },
            )

    async def _answer_inner(
        self,
        *,
        query: str,
        intent: IntentUnderstandingResult | None,
        conversation_id: str | None,
        project_memory_block: str | None = None,
        knowledge_notes_block: str | None = None,
    ) -> SimpleQueryResult:
        started = time.monotonic()
        search_q = self._build_search_query(query, intent)
        start_date = cutoff_iso(self._max_age_months)
        hint = freshness_query_hint(self._max_age_months)
        if hint not in search_q:
            search_q = f"{search_q} {hint}".strip()

        tavily = await self._search(
            query=search_q,
            max_results=self._max_results,
            search_depth="basic",
            include_raw_content=False,
            start_date=start_date,
        )

        if tavily.error and not tavily.items:
            return SimpleQueryResult(
                answer_markdown=(
                    f"检索未能完成：{tavily.error}"
                    if tavily.status != "no_api_key"
                    else "未配置搜索服务，暂时无法回答信息查询。请配置 TAVILY_API_KEY 后重试。"
                ),
                sources=[],
                confidence=0.1,
                metadata={
                    "query_mode": "information_query",
                    "error": tavily.status,
                    "search_query": search_q,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "conversation_id": conversation_id,
                },
            )

        cutoff = start_date
        filtered = self._filter_by_cutoff(tavily.items, cutoff)
        sources = [
            QuerySource(
                title=str(it.get("title") or "")[:200],
                url=str(it.get("url") or ""),
                snippet=str(it.get("content") or "")[:280],
                published_date=str(it.get("published_date") or "")[:10],
            )
            for it in filtered
            if it.get("url")
        ][: self._max_results]

        if not sources:
            return SimpleQueryResult(
                answer_markdown="未找到足够公开信息。可以换个问法，或改用「请帮我收集…」做资料汇总。",
                sources=[],
                confidence=0.2,
                metadata={
                    "query_mode": "information_query",
                    "search_query": search_q,
                    "hit_count": 0,
                    "filtered_expired": max(0, len(tavily.items) - len(filtered)),
                    "evidence_cutoff_date": cutoff,
                    "elapsed_ms": int((time.monotonic() - started) * 1000),
                    "conversation_id": conversation_id,
                },
            )

        answer = await self._summarize(
            query=query,
            sources=sources,
            project_memory_block=project_memory_block,
            knowledge_notes_block=knowledge_notes_block,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return SimpleQueryResult(
            answer_markdown=answer,
            sources=sources,
            confidence=0.7 if len(sources) >= 2 else 0.5,
            metadata={
                "query_mode": "information_query",
                "search_query": search_q,
                "hit_count": len(sources),
                "filtered_expired": max(0, len(tavily.items) - len(filtered)),
                "evidence_cutoff_date": cutoff,
                "elapsed_ms": elapsed_ms,
                "conversation_id": conversation_id,
            },
        )

    @staticmethod
    def _build_search_query(query: str, intent: IntentUnderstandingResult | None) -> str:
        parts: list[str] = []
        if intent:
            if intent.company:
                parts.append(intent.company)
            if intent.product and intent.product not in (intent.company or ""):
                parts.append(intent.product)
        q = (query or "").strip()
        if q and q not in " ".join(parts):
            parts.append(q)
        return " ".join(parts).strip() or q

    @staticmethod
    def _filter_by_cutoff(items: list[dict], cutoff_iso_str: str) -> list[dict]:
        kept: list[dict] = []
        for it in items:
            raw = str(it.get("published_date") or "").strip()
            if not raw:
                kept.append(it)
                continue
            try:
                d = datetime.strptime(raw[:10], "%Y-%m-%d").date()
                c = datetime.strptime(cutoff_iso_str[:10], "%Y-%m-%d").date()
                if d < c:
                    continue
            except ValueError:
                pass
            kept.append(it)
        return kept

    async def _summarize(
        self,
        *,
        query: str,
        sources: list[QuerySource],
        project_memory_block: str | None = None,
        knowledge_notes_block: str | None = None,
    ) -> str:
        lines = []
        for i, s in enumerate(sources, 1):
            date_note = s.published_date or "日期未知"
            lines.append(
                f"[{i}] {s.title}\nURL: {s.url}\n日期: {date_note}\n摘要: {s.snippet}"
            )
        context_section = ""
        if project_memory_block:
            context_section += f"{project_memory_block}\n\n"
        if knowledge_notes_block:
            context_section += f"{knowledge_notes_block}\n\n"
        user_prompt = (
            f"{context_section}"
            f"## 用户问题\n{query}\n\n"
            f"## 检索结果\n" + "\n\n".join(lines) + "\n\n"
            "请用中文给出简短回答，并在文末用 Markdown 列表列出可用来源（标题+链接）。"
            "仅使用上列 URL，禁止虚构。项目记忆与企业笔记仅作背景，不可伪造成公开来源；"
            "引用笔记时标明「内部笔记」。"
        )
        if self._llm_generate:
            resp = await self._llm_generate(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
            )
        else:
            resp = await self._llm.generate(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.3,
            )
        content = (resp.content or "").strip()
        if not content:
            # Fallback: bullet list from sources only
            bullets = "\n".join(
                f"- [{s.title or s.url}]({s.url})" for s in sources if s.url
            )
            return f"未生成摘要。可参考以下来源：\n\n{bullets}"
        return content
