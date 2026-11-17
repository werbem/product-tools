"""Source Router — dispatches ResearchTasks to matching ResearchSources.

Responsibilities:
  1. Maintain a registry of available ResearchSources
  2. Match ResearchTasks by source_type → list of sources
  3. Route by analysis dimensions → source types (via DimensionRouter)
  4. Execute all matched sources in parallel (asyncio.gather)
  5. Deduplicate results by URL across sources
  6. Provide a unified SourceResult list back to Research Agent

Two routing modes:
  A) route_by_dimensions(plan)  — dimension-based (NEW: primary mode)
  B) search_many(tasks)         — task.source_type-based (legacy, kept for compat)
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from app.application.dto.agent_dto import ResearchPlan, ResearchTask
from app.infrastructure.tools.dimension_router import DimensionRouter, SourceExecutionPlan, dimension_router as _dim_router
from app.infrastructure.tools.research_source import (
    EvidenceItem,
    ResearchSource,
    SourceResult,
    SourceType,
)
from app.application.services.intent_entities import sanitize_search_keywords
from app.infrastructure.tools.sources.tavily_source import tavily_source
from app.infrastructure.tools.sources.appstore_source import appstore_source
from app.infrastructure.tools.sources.googleplay_source import googleplay_source
from app.infrastructure.tools.sources.official_source import official_source
from app.infrastructure.tools.sources.news_source import news_source
from app.infrastructure.tools.sources.community_source import community_source
from app.infrastructure.tools.sources.github_source import github_source
from app.infrastructure.trace import trace_collector, TraceStatus


# ── Source type → ResearchSource mapping ──
_SOURCE_REGISTRY: dict[str, list[ResearchSource]] = {
    SourceType.WEB: [tavily_source],
    SourceType.NEWS: [news_source],
    SourceType.APP_STORE: [appstore_source, googleplay_source],
    SourceType.SOCIAL: [community_source],
    SourceType.DEVELOPER: [github_source],
    SourceType.OFFICIAL: [official_source],
}

# Aliases that Planner may emit
_SOURCE_ALIASES: dict[str, str] = {
    "ai_search": SourceType.WEB,
}


class SourceRouter:
    """Routes ResearchTasks to ResearchSources and executes them in parallel."""

    def __init__(self, dim_router: Optional[DimensionRouter] = None):
        self._registry: dict[str, list[ResearchSource]] = dict(_SOURCE_REGISTRY)
        self._dim_router = dim_router or _dim_router

    # ── Registration ──

    def register(self, source_type: str, source: ResearchSource) -> None:
        if source_type not in self._registry:
            self._registry[source_type] = []
        self._registry[source_type].append(source)

    def get_sources(self, source_type: str) -> list[ResearchSource]:
        resolved = _SOURCE_ALIASES.get(source_type, source_type)
        return self._registry.get(resolved, self._registry.get(SourceType.WEB, []))

    # ═══════════════════════════════════════════════════
    #  Mode A: Dimension-based routing (PRIMARY)
    # ═══════════════════════════════════════════════════

    def route_by_dimensions(
        self,
        research_plan: ResearchPlan,
    ) -> SourceExecutionPlan:
        """Select source types based on analysis dimensions.

        Uses DimensionRouter to map dimension names → source types.
        Falls back to research_tasks source_type if no dimensions specified.

        Args:
            research_plan: Planner output (analysis_scope + keywords + objective)

        Returns:
            SourceExecutionPlan with resolved source types
        """
        if isinstance(research_plan, dict):
            dimensions = research_plan.get("analysis_scope", []) or []
            objective = research_plan.get("objective", "") or ""
        else:
            dimensions = research_plan.analysis_scope if research_plan.analysis_scope else []
            objective = research_plan.objective if research_plan.objective else ""
        keywords = self._collect_keywords(research_plan)

        if dimensions:
            plan = self._dim_router.build(dimensions, keywords, objective)
        else:
            # Fallback: use task source_types directly
            rts = research_plan.get("research_tasks", []) if isinstance(research_plan, dict) else research_plan.research_tasks
            source_types = list({t.get("source_type") if isinstance(t, dict) else t.source_type for t in rts})
            plan = SourceExecutionPlan(
                dimensions=[],
                source_types=source_types if source_types else [SourceType.WEB],
                keywords=keywords,
                objective=objective,
                dimension_mapping={"fallback": source_types or [SourceType.WEB]},
            )

        return plan

    async def execute_plan(
        self,
        plan: SourceExecutionPlan,
        context: Optional[dict] = None,
        max_concurrency: int = 10,
    ) -> list[SourceResult]:
        """Execute a SourceExecutionPlan across all matched sources.

        For each source_type in the plan, calls all registered ResearchSources
        with the plan's keywords. Executes in parallel with concurrency control.

        Args:
            plan: SourceExecutionPlan from route_by_dimensions()
            context: Metadata dict (task_id, etc.)
            max_concurrency: Max concurrent source executions

        Returns:
            List of SourceResult from all executed sources
        """
        if not plan.source_types:
            return []

        # Build (source, query) pairs
        executions: list[tuple[ResearchSource, str, str]] = []
        for stype in plan.source_types:
            sources = self.get_sources(stype)
            if not sources:
                continue
            for source in sources:
                # Build a combined query from multiple keywords for better coverage
                if plan.keywords:
                    cleaned = sanitize_search_keywords(list(plan.keywords)[:8])
                    kw = " ".join(cleaned[:5]) if cleaned else (plan.objective or "")
                else:
                    kw = plan.objective
                executions.append((source, kw, stype))

        if not executions:
            return []

        # Execute in parallel
        sem = asyncio.Semaphore(max_concurrency)

        async def _execute_one(source: ResearchSource, query: str, stype: str) -> SourceResult:
            async with sem:
                start = time.time()
                try:
                    result = await source.search(query=query, context=context)
                    return result
                except Exception as exc:
                    duration_ms = int((time.time() - start) * 1000)
                    return SourceResult(
                        items=[],
                        source_type=stype,
                        source_name=source.name,
                        status="error",
                        error=f"{type(exc).__name__}: {exc}",
                        total_found=0,
                        duration_ms=duration_ms,
                    )

        coros = [_execute_one(source, query, stype) for source, query, stype in executions]
        return list(await asyncio.gather(*coros))

    # ═══════════════════════════════════════════════════
    #  Mode B: Task source_type-based (legacy compat)
    # ═══════════════════════════════════════════════════

    async def search_many(
        self,
        tasks: list[ResearchTask],
        context: Optional[dict] = None,
        max_concurrency: int = 10,
    ) -> list[SourceResult]:
        if not tasks:
            return []

        executions: list[tuple[ResearchSource, str, str]] = []
        for task in tasks:
            sources = self.get_sources(task.source_type)
            if not sources:
                continue
            for source in sources:
                for kw in task.keywords[:3]:
                    executions.append((source, kw, task.source_type))

        if not executions:
            return []

        sem = asyncio.Semaphore(max_concurrency)

        async def _execute_one(source: ResearchSource, query: str, stype: str) -> SourceResult:
            async with sem:
                start = time.time()
                try:
                    result = await source.search(query=query, context=context)
                    return result
                except Exception as exc:
                    duration_ms = int((time.time() - start) * 1000)
                    return SourceResult(
                        items=[], source_type=stype, source_name=source.name,
                        status="error", error=f"{type(exc).__name__}: {exc}",
                        total_found=0, duration_ms=duration_ms,
                    )

        coros = [_execute_one(source, query, stype) for source, query, stype in executions]
        return list(await asyncio.gather(*coros))

    # ── Utilities ──

    @staticmethod
    def _collect_keywords(plan) -> list[str]:
        """Collect all unique keywords from research_tasks (dict-safe)."""
        seen: set[str] = set()
        result: list[str] = []
        if plan is None:
            return result
        tasks = plan.get("research_tasks", []) if isinstance(plan, dict) else getattr(plan, "research_tasks", [])
        for task in tasks:
            if isinstance(task, dict):
                kws = task.get("keywords", []) or []
            else:
                kws = getattr(task, "keywords", []) or []
            for kw in sanitize_search_keywords(list(kws)):
                if kw not in seen:
                    seen.add(kw)
                    result.append(kw)
        return result
    @staticmethod
    def deduplicate(results: list[SourceResult]) -> list[EvidenceItem]:
        seen_urls: set[str] = set()
        deduped: list[EvidenceItem] = []
        for result in results:
            if not result.is_success or result.is_empty:
                continue
            for item in result.items:
                if item.url and item.url in seen_urls:
                    continue
                if item.url:
                    seen_urls.add(item.url)
                deduped.append(item)
        return deduped


# ── Singleton ──

source_router = SourceRouter()
