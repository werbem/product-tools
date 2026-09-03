"""LLM-Driven Source Router — semantic source selection via LLM.

Upgrades the rule-based SourceSelectionEngine to an LLM-powered router.

Design:
  - LLM receives ResearchPlan + Source Profiles → reasons about which sources to use
  - Considered factors: cost (free preferred), quality (high-confidence preferred),
    relevance (dimension→source matching)
  - Outputs structured ResearchExecutionPlan (same interface as rule-based)
  - Falls back to rule-based SourceSelectionEngine if LLM fails

Prompt version management:
  - PromptV1: initial version
  - Future versions can be added with version tags
  - Each version tracks: creation date, description, prompt template

Architecture:
  ResearchPlan
      ↓
  LLMRouter.route()          ← NEW: LLM-powered semantic routing
      ↓
  ResearchExecutionPlan      ← SAME: output format unchanged
      ↓
  SourceRouter.execute_plan() ← UNCHANGED: execution unchanged
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field

from app.infrastructure.llm.client import LLMResponse, llm_client
from app.infrastructure.tools.research_source import SourceType
from app.infrastructure.tools.source_selection import (
    ResearchExecutionPlan,
    SelectionTask,
    source_selection,
)
from app.infrastructure.trace import trace_collector

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════
#  Source Profiles — describes each source to the LLM
# ═══════════════════════════════════════════════════

@dataclass
class SourceProfile:
    """Describe a research source for LLM reasoning."""
    source_type: str
    name: str
    description: str
    cost: str          # "free" | "api_required" | "rate_limited_free"
    quality: str       # "high" | "medium"
    best_for: list[str]  # What this source is best for
    not_for: list[str]   # What this source should NOT be used for


SOURCE_PROFILES: list[SourceProfile] = [
    SourceProfile(
        source_type=SourceType.WEB,
        name="Tavily Web Search",
        description="通用网页搜索，获取新闻、文章、公开报告",
        cost="api_required",
        quality="high",
        best_for=["产品功能", "市场分析", "竞争情报", "商业模式研究"],
        not_for=["用户反馈", "代码分析", "App评分"],
    ),
    SourceProfile(
        source_type=SourceType.APP_STORE,
        name="Apple App Store / Google Play",
        description="获取App评分、用户评论、版本更新历史",
        cost="free",
        quality="high",
        best_for=["用户体验", "用户反馈", "产品评价", "评分分析"],
        not_for=["技术架构", "商业模式深层分析", "B端产品"],
    ),
    SourceProfile(
        source_type=SourceType.SOCIAL,
        name="Community (知乎/Reddit/小红书)",
        description="获取社区用户讨论、口碑、情感倾向",
        cost="free",
        quality="medium",
        best_for=["用户反馈", "口碑分析", "情感分析", "使用场景"],
        not_for=["技术指标", "精确数据", "财务信息"],
    ),
    SourceProfile(
        source_type=SourceType.OFFICIAL,
        name="Official Website",
        description="获取官网产品介绍、定价、功能列表、公司战略",
        cost="free",
        quality="high",
        best_for=["产品定位", "产品功能", "商业模式", "定价策略"],
        not_for=["用户评价", "第三方评测"],
    ),
    SourceProfile(
        source_type=SourceType.NEWS,
        name="News (Google News / Bing News)",
        description="获取最新新闻、行业动态、公司公告",
        cost="free",
        quality="high",
        best_for=["增长策略", "市场变化", "融资消息", "战略调整"],
        not_for=["深度技术分析", "用户反馈"],
    ),
    SourceProfile(
        source_type=SourceType.DEVELOPER,
        name="GitHub",
        description="获取开源项目信息、技术栈、开发者活跃度",
        cost="free",
        quality="high",
        best_for=["技术能力", "开发者生态", "代码质量", "开源贡献"],
        not_for=["用户反馈", "商业数据", "营销策略"],
    ),
]


def _build_source_profiles_text() -> str:
    """Build a formatted text describing all sources for the LLM prompt."""
    lines = []
    for sp in SOURCE_PROFILES:
        lines.append(
            f"- **{sp.name}** ({sp.source_type})\n"
            f"  描述: {sp.description}\n"
            f"  成本: {sp.cost} | 质量: {sp.quality}\n"
            f"  最适合: {', '.join(sp.best_for)}\n"
            f"  不适合: {', '.join(sp.not_for)}"
        )
    return "\n".join(lines)


# ═══════════════════════════════════════════════════
#  Pydantic Models for LLM Structured Output
# ═══════════════════════════════════════════════════

class LLMRouterTask(BaseModel):
    """A single research task decided by LLM."""
    dimension: str = Field(description="研究维度名称")
    sources: list[str] = Field(description="选择的数据源类型列表")
    keywords: list[str] = Field(description="搜索关键词")
    priority: int = Field(default=3, ge=1, le=5, description="优先级 1-5")
    expected_evidence: str = Field(description="预期获取什么类型的证据")
    reasoning: str = Field(description="为什么选择这些数据源")


class LLMRouterOutput(BaseModel):
    """LLM structured output for source routing."""
    tasks: list[LLMRouterTask] = Field(description="研究任务列表")
    unused_sources: list[str] = Field(default_factory=list, description="有意不使用的源及原因")
    routing_strategy: str = Field(description="整体路由策略说明")


# ═══════════════════════════════════════════════════
#  Prompt Templates (versioned)
# ═══════════════════════════════════════════════════

@dataclass
class RouterPromptVersion:
    """Versioned prompt template for LLM routing."""
    version: str
    created: str
    description: str
    system_prompt: str


# ── V1: Initial LLM Router Prompt ──
ROUTER_PROMPT_V1 = RouterPromptVersion(
    version="v1",
    created="2026-07-18",
    description="Initial LLM-driven source router with cost/quality/relevance constraints",
    system_prompt="""你是竞品分析数据源选择专家。你的任务是根据研究目标，为每个研究维度选择最合适的数据源。

## 核心原则

1. **成本优先**: 优先使用免费数据源（app_store, social, official, news, developer），仅在必要时使用付费API（web/Tavily）
2. **质量优先**: 优先选择高可信度数据源（high > medium）
3. **相关性**: 数据源必须与当前研究维度高度相关
4. **避免浪费**: 不选择与研究维度无关的数据源

## 数据源目录

{sources_catalog}

## 输出要求

为每个研究维度选择 1-3 个最相关数据源（不要选太多），并说明：
- 为什么选这些（简要推理）
- 预期获取什么类型的证据
- 优先级的理由

## 路由策略示例

- "分析飞猪DAU下降" → 用户体验维度选 App Store（用户评价）+ Community（口碑）+ 可能需要 Tavily（竞品动态）
- "分析Notion商业模式" → Official Website（定价页）+ News（融资新闻）+ Tavily（行业报告）
- "分析Cursor增长" → News（增长报道）+ Community（开发者口碑）+ Tavily（行业分析）

注意：GitHub 只用于技术能力分析，不要滥用。""",
)

# Active prompt version
ACTIVE_ROUTER_PROMPT = ROUTER_PROMPT_V1


# ═══════════════════════════════════════════════════
#  LLM Router
# ═══════════════════════════════════════════════════

class LLMRouter:
    """LLM-driven source router.

    Replaces rule-based keyword matching with semantic LLM reasoning
    about which sources to use for each research dimension.

    Fallback: if LLM call fails, falls back to rule-based SourceSelectionEngine.
    """

    def __init__(self, prompt_version: Optional[RouterPromptVersion] = None):
        self._prompt = prompt_version or ACTIVE_ROUTER_PROMPT
        self._fallback = source_selection

    @property
    def prompt_version(self) -> str:
        return self._prompt.version

    @property
    def prompt_description(self) -> str:
        return self._prompt.description

    async def route(
        self,
        dimensions: list[str],
        keywords: list[str],
        objective: str,
        task_id: str = "",
    ) -> ResearchExecutionPlan:
        """Route research dimensions to sources using LLM semantic reasoning.

        Args:
            dimensions: Analysis dimension names from Planner
            keywords: Search keywords from Planner
            objective: Analysis objective description
            task_id: Task ID for trace correlation

        Returns:
            ResearchExecutionPlan with LLM-selected source assignments
        """
        if not dimensions:
            return self._fallback.build_plan(dimensions, keywords, objective)

        # Build user prompt
        user_prompt = self._build_user_prompt(dimensions, keywords, objective)

        # Build system prompt with source catalog
        system_prompt = self._prompt.system_prompt.format(
            sources_catalog=_build_source_profiles_text(),
        )

        # --- Trace ---
        trace = trace_collector.start_trace(
            task_id=task_id,
            stage="llm_router",
            agent_name="research",
            input_summary=f"dimensions={dimensions[:3]}, objective={objective[:80]}",
            metadata={
                "prompt_version": self._prompt.version,
                "dimensions": dimensions,
                "keywords": keywords[:5],
            },
        )

        start = time.time()
        try:
            response: LLMResponse = await llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=LLMRouterOutput,
                temperature=0.3,  # Lower temperature for deterministic routing
            )

            duration_ms = int((time.time() - start) * 1000)

            if response.parsed and isinstance(response.parsed, LLMRouterOutput):
                plan = self._convert_to_plan(
                    response.parsed, dimensions, keywords, objective,
                )
                trace_collector.end_trace(
                    trace,
                    success=True,
                    output_summary=f"LLM routed {len(plan.tasks)} tasks to {plan.all_source_types}",
                    metadata={
                        "duration_ms": duration_ms,
                        "llm_model": response.model,
                        "tasks": len(plan.tasks),
                        "sources": plan.all_source_types,
                        "prompt_version": self._prompt.version,
                    },
                )
                return plan

            # Parsed but wrong type — fallback
            raise ValueError(f"LLM returned unexpected type: {type(response.parsed)}")

        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            is_timeout = isinstance(exc, (TimeoutError, asyncio.TimeoutError)) or (
                "timeout" in str(exc).lower() or "[TIMEOUT]" in str(exc)
            )
            logger.warning(
                "llm_router %s, falling back to rule-based: %s",
                "timed_out" if is_timeout else "failed",
                exc,
            )
            trace_collector.end_trace(
                trace,
                success=False,
                output_summary=(
                    "LLM routing timed out, rule fallback"
                    if is_timeout
                    else "LLM routing failed, falling back to rule-based"
                ),
                error=str(exc),
                metadata={
                    "duration_ms": duration_ms,
                    "fallback": True,
                    "timeout": is_timeout,
                },
            )

            # Fallback to rule-based selection
            return self._fallback.build_plan(dimensions, keywords, objective)

    # ── Internals ──

    def _build_user_prompt(
        self,
        dimensions: list[str],
        keywords: list[str],
        objective: str,
    ) -> str:
        dims_text = "\n".join(f"  {i+1}. {d}" for i, d in enumerate(dimensions))
        kws_text = ", ".join(keywords) if keywords else "(无)"
        return (
            f"## 分析目标\n{objective}\n\n"
            f"## 研究维度\n{dims_text}\n\n"
            f"## 已有搜索关键词\n{kws_text}\n\n"
            "请为每个研究维度选择合适的数据源（1-3个），"
            "优先使用免费高可信度数据源。"
        )

    def _convert_to_plan(
        self,
        llm_output: LLMRouterOutput,
        dimensions: list[str],
        keywords: list[str],
        objective: str,
    ) -> ResearchExecutionPlan:
        """Convert LLM structured output to ResearchExecutionPlan."""
        tasks: list[SelectionTask] = []
        all_sources: set[str] = set()

        for idx, llm_task in enumerate(llm_output.tasks):
            sources = llm_task.sources
            all_sources.update(sources)

            kw = llm_task.keywords if llm_task.keywords else keywords[:3]

            tasks.append(SelectionTask(
                dimension=llm_task.dimension,
                sources=sources,
                keywords=kw,
                priority=llm_task.priority,
            ))

        # Always add unused dimensions with rule-based fallback
        covered_dims = {t.dimension for t in llm_output.tasks}
        for dim in dimensions:
            if dim not in covered_dims:
                fallback = self._fallback
                fb_plan = fallback.build_plan([dim], keywords, objective)
                for ft in fb_plan.tasks:
                    tasks.append(ft)
                    all_sources.update(ft.sources)

        return ResearchExecutionPlan(
            objective=objective,
            dimensions=list(dimensions),
            tasks=tasks,
            all_source_types=sorted(all_sources),
        )


# ── Singleton ──

llm_router = LLMRouter()
