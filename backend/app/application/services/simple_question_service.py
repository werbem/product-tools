"""Simple factoid questions — context or light search, no long workflows (Phase 2 Step 5)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.follow_up_service import (
    extract_prior_refs,
    message_has_prior_artifact,
)
from app.application.services.simple_query_service import (
    QuerySource,
    SimpleQueryService,
)
from app.domain.entities.message import Message
from app.infrastructure.llm.client import LLMClient, LLMResponse, llm_client

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_S = 40.0
_MAX_CONTEXT_CHARS = 2200

_SYSTEM_CONTEXT = """你是竞品分析助手的简单问答模块。
仅根据「已有上下文」用中文短答：
- ≤300 字或 ≤5 条 bullet
- 不编造上下文没有的事实或链接
- 不要输出完整竞品分析报告结构
- 信息不足时明说「根据现有材料无法确定」"""

_SYSTEM_SEARCH = """你是竞品分析助手的简单问答模块。
根据检索片段短答：
- ≤300 字或 ≤5 条 bullet
- 只使用给定来源；不要虚构链接
- 不要输出十三章报告
- 来源无日期时不要断言「最新」"""


class SimpleQuestionResult(BaseModel):
    answer_markdown: str
    sources: list[QuerySource] = Field(default_factory=list)
    confidence: float = 0.5
    question_mode: str = "llm_only"  # context_only | light_search | llm_only | guide
    metadata: dict[str, Any] = Field(default_factory=dict)


LlmGenerateFn = Callable[..., Awaitable[LLMResponse]]


class SimpleQuestionService:
    def __init__(
        self,
        *,
        query_service: SimpleQueryService | None = None,
        llm: LLMClient | None = None,
        llm_generate: LlmGenerateFn | None = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        # Reuse SimpleQueryService for light Tavily (max_results=3)
        self._query = query_service or SimpleQueryService(
            max_results=3,
            timeout_s=min(float(timeout_s), 35.0),
        )
        self._llm = llm or llm_client
        self._llm_generate = llm_generate
        self._timeout_s = float(timeout_s)

    async def answer(
        self,
        *,
        query: str,
        intent: IntentUnderstandingResult | None = None,
        messages: list[Message] | None = None,
        conversation_id: str | None = None,
        project_memory_block: str | None = None,
        knowledge_notes_block: str | None = None,
    ) -> SimpleQuestionResult:
        started = time.monotonic()
        try:
            return await asyncio.wait_for(
                self._answer_inner(
                    query=query,
                    intent=intent,
                    messages=messages or [],
                    conversation_id=conversation_id,
                    project_memory_block=project_memory_block,
                    knowledge_notes_block=knowledge_notes_block,
                ),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            return SimpleQuestionResult(
                answer_markdown="回答超时，请稍后重试，或改用「最近有什么变化」/「做竞品分析报告」。",
                question_mode="guide",
                confidence=0.1,
                metadata={"error": "timeout", "elapsed_ms": int((time.monotonic() - started) * 1000)},
            )
        except Exception as exc:
            logger.exception("simple_question failed: %s", exc)
            return SimpleQuestionResult(
                answer_markdown="暂时无法回答该问题，请稍后重试。",
                question_mode="guide",
                confidence=0.1,
                metadata={"error": type(exc).__name__},
            )

    async def _answer_inner(
        self,
        *,
        query: str,
        intent: IntentUnderstandingResult | None,
        messages: list[Message],
        conversation_id: str | None,
        project_memory_block: str | None = None,
        knowledge_notes_block: str | None = None,
    ) -> SimpleQuestionResult:
        has_prior = (
            message_has_prior_artifact(messages)
            or bool(project_memory_block)
            or bool(knowledge_notes_block)
        )
        if has_prior:
            context = self._build_context_blob(messages, intent)
            if project_memory_block:
                context = f"{project_memory_block}\n\n{context}".strip()
            if knowledge_notes_block:
                context = f"{knowledge_notes_block}\n\n{context}".strip()
            answer = await self._llm_short(
                system=_SYSTEM_CONTEXT,
                user=(
                    f"## 已有上下文\n{context}\n\n"
                    f"## 用户问题\n{query}\n\n"
                    "请短答。若引用企业知识笔记，须标明「内部笔记」。"
                ),
            )
            refs = extract_prior_refs(messages)
            return SimpleQuestionResult(
                answer_markdown=answer,
                sources=[],
                confidence=0.75,
                question_mode="context_only",
                metadata={
                    "conversation_id": conversation_id,
                    "prior_task_id": refs.get("prior_task_id"),
                    "prior_report_id": refs.get("prior_report_id"),
                },
            )

        company = (intent.company if intent else None) or ""
        if company.strip():
            # Light search via SimpleQueryService subset
            q_result = await self._query.answer(
                query=query,
                intent=intent,
                conversation_id=conversation_id,
                project_memory_block=project_memory_block,
                knowledge_notes_block=knowledge_notes_block,
            )
            # Re-summarize shorter if query returned a long answer — keep query answer if ok
            answer = q_result.answer_markdown
            if len(answer) > 500:
                answer = await self._llm_short(
                    system=_SYSTEM_SEARCH,
                    user=(
                        f"## 问题\n{query}\n\n"
                        f"## 材料\n{answer[:1800]}\n\n请压缩为 ≤300 字短答，保留关键来源链接。"
                    ),
                )
            return SimpleQuestionResult(
                answer_markdown=answer,
                sources=list(q_result.sources),
                confidence=max(0.45, float(q_result.confidence or 0.5)),
                question_mode="light_search",
                metadata={
                    "conversation_id": conversation_id,
                    "query_metadata": q_result.metadata,
                },
            )

        # No prior, no company entity
        return SimpleQuestionResult(
            answer_markdown=(
                "请补充要了解的公司或竞品名称。"
                "也可以问「××最近有什么变化」，或「请做××与××的竞品分析报告」。"
            ),
            sources=[],
            confidence=0.3,
            question_mode="guide",
            metadata={"conversation_id": conversation_id, "reason": "no_entity_no_prior"},
        )

    @staticmethod
    def _build_context_blob(
        messages: list[Message],
        intent: IntentUnderstandingResult | None,
    ) -> str:
        parts: list[str] = []
        if intent and (intent.company or intent.product):
            comps = "、".join(intent.competitors or [])
            parts.append(
                f"实体：{intent.company or '?'} / {intent.product or '?'}；竞品：{comps or '?'}"
            )
        refs = extract_prior_refs(messages)
        if refs.get("prior_task_id"):
            parts.append(f"prior_task_id={refs['prior_task_id']}")
        blob = str(refs.get("prior_assistant_blob") or "")
        if blob:
            parts.append("上轮助手内容：\n" + blob[:_MAX_CONTEXT_CHARS])
        else:
            for message in reversed(list(messages or [])[-6:]):
                if message.role == "assistant" and (message.content or "").strip():
                    parts.append((message.content or "")[:_MAX_CONTEXT_CHARS])
                    break
        # Try report excerpt via FollowUpService helper path
        try:
            from app.application.services.follow_up_service import FollowUpService

            tmp = FollowUpService()
            report = tmp._load_report_excerpt(
                refs.get("prior_task_id"),
                refs.get("prior_report_id"),
            )
            if report:
                parts.append("报告摘要：\n" + report[:_MAX_CONTEXT_CHARS])
        except Exception:
            pass
        return "\n\n".join(parts).strip() or "（无上下文）"

    async def _llm_short(self, *, system: str, user: str) -> str:
        try:
            if self._llm_generate:
                resp = await self._llm_generate(
                    system_prompt=system,
                    user_prompt=user,
                    temperature=0.2,
                )
            else:
                resp = await self._llm.generate(
                    system_prompt=system,
                    user_prompt=user,
                    temperature=0.2,
                )
            content = (resp.content or "").strip()
            if content:
                return content
        except Exception as exc:
            logger.debug("simple_question llm failed: %s", exc)
        return "根据现有材料无法给出可靠短答，请补充信息或换一种问法。"
