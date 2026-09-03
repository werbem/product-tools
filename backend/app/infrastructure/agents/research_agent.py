"""Research Agent — multi-source evidence collection + LLM extraction.

Flow:
  1. Read research_tasks from Planner's ResearchPlan
  2. Route tasks via SourceRouter → multiple ResearchSources (parallel)
  3. LLM extracts structured evidence from search results
  4. Build EvidenceBundle + QualityReport

Rules:
  - No fabricated sources: every evidence must have a real URL
  - No evidence → return empty list (never invent)
  - Source coverage expands as new ResearchSources are registered
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from typing import Any

from app.application.dto.agent_dto import (
    CompanyInfoDTO,
    EvidenceBundleDTO,
    EvidenceItemDTO,
    ProductInfoDTO,
    QualityReport,
    ResearchInput,
    ResearchOutput,
)
from app.config.constants import Phase
from app.infrastructure.agents.base import AgentContext, AgentResult, BaseAgent
from app.infrastructure.agents.research_prompt import (
    EvidenceItem,
    ExtractedEvidence,
    SYSTEM_PROMPT,
    build_extraction_prompt,
)
from app.infrastructure.llm.client import llm_client
from app.infrastructure.tools.research_source import SourceResult
from app.infrastructure.tools.source_router import source_router
from app.infrastructure.tools.source_selection import source_selection
from app.infrastructure.tools.llm_router import llm_router
from app.infrastructure.workflow.progress_hints import (
    RAW_TIMEOUT_FALLBACK_HINT,
    RESEARCH_PROGRESS_HINTS,
)


logger = logging.getLogger(__name__)


def _dget(obj, key, default=None):
    """Safe dict/object access."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class ResearchAgent(BaseAgent[ResearchInput, ResearchOutput]):
    """Research Agent — multi-source evidence collection.

    Routes Planner's ResearchTasks to registered ResearchSources,
    collects evidence in parallel, and extracts structured data via LLM.
    """

    def __init__(self) -> None:
        self._partial_evidence_items: list[EvidenceItemDTO] = []
        self._partial_all_results: list[SourceResult] = []
        self._partial_input_data: ResearchInput | None = None
        self._partial_fallback_meta: dict[str, Any] = {}
        self._partial_task_id: str = ""
        self._last_cap_meta: dict[str, Any] = {}
        self._last_freshness_meta: dict[str, Any] = {}

    def has_partial_results(self) -> bool:
        return bool(self._partial_evidence_items or self._partial_all_results)

    async def build_partial_result(self) -> AgentResult | None:
        """Build output from the latest in-progress snapshot (used on node timeout).

        Priority:
          1. Already-extracted evidence (optionally topped up with unused raw URLs)
          2. Raw search → minimal evidence fallback
          3. Empty evidence (only when no raw items either)
        """
        if self._partial_input_data is None:
            return None

        input_data = self._partial_input_data
        all_results = list(self._partial_all_results)
        evidence_items = list(self._partial_evidence_items)
        fallback_meta: dict[str, Any] = {
            "research_timeout": True,
            "sources_succeeded": sum(1 for r in all_results if r.status == "success"),
        }

        if evidence_items:
            evidence_items, topup_n = self._top_up_evidence_with_raw(
                evidence_items, all_results, input_data,
            )
            if topup_n:
                fallback_meta["evidence_fallback"] = "raw_search"
                fallback_meta["raw_items_converted"] = topup_n
        else:
            converted, n = self._convert_raw_results_to_evidence(
                all_results, input_data, mark_timeout_fallback=True,
            )
            evidence_items = converted
            if n > 0:
                fallback_meta["evidence_fallback"] = "raw_search"
                fallback_meta["raw_items_converted"] = n
                self._touch_research_progress(
                    self._partial_task_id,
                    36.0,
                    RAW_TIMEOUT_FALLBACK_HINT,
                )

        self._partial_evidence_items = list(evidence_items)
        self._partial_fallback_meta = dict(fallback_meta)

        evidence_items = await self._apply_date_and_freshness_pipeline(
            evidence_items, input_data,
        )
        self._partial_evidence_items = list(evidence_items)

        bundle, quality = self._build_output(
            input_data,
            evidence_items,
            all_results,
        )
        quality.research_timeout = True
        quality.missing_data_warnings = list(quality.missing_data_warnings) + [
            "Research 阶段超时，返回已收集的部分证据",
        ]
        if fallback_meta.get("evidence_fallback") == "raw_search":
            quality.fallback_used = True
            quality.evidence_fallback = "raw_search"
            quality.raw_items_converted = int(fallback_meta.get("raw_items_converted") or 0)
            quality.missing_data_warnings = list(quality.missing_data_warnings) + [
                f"抽取超时，已将 {quality.raw_items_converted} 条原始搜索结果降级为证据",
            ]

        output = ResearchOutput(evidence_bundle=bundle, quality_report=quality)
        freshness_meta = getattr(self, "_last_freshness_meta", {}) or {}
        return AgentResult(
            success=True,
            output=output,
            phase_record={
                "phase": Phase.RESEARCHING.value,
                "status": "completed",
                "error": "research_partial_on_timeout",
                "evidence_count": len(evidence_items),
                **fallback_meta,
                **freshness_meta,
            },
        )

    @property
    def agent_name(self) -> str:
        return "research"

    @property
    def phase(self) -> Phase:
        return Phase.RESEARCHING

    # ── Temporal ranking helpers (P0: source-date passthrough + freshness fix) ──

    _TEMPORAL_RANK: dict[str, int] = {
        "recent": 0,
        "aging": 1,
        "unknown": 2,
        "stale": 3,
        "historical": 4,
    }

    @staticmethod
    def _parse_date(date_str: str) -> datetime | None:
        """Parse common date formats. Returns None when unparseable/empty."""
        if not date_str:
            return None
        text = str(date_str).strip()
        formats = [
            "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S",
            "%Y年%m月%d日", "%b %d, %Y", "%d %b %Y",
            "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
        ]
        for fmt in formats:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None

    @classmethod
    def _compute_temporal_level(cls, date_str: str) -> str:
        """Derive temporal level from a date string.

        recent       < 1 year
        aging        1-3 years
        stale        3-5 years
        historical   >= 5 years
        unknown      no/unparseable date
        """
        dt = cls._parse_date(date_str)
        if dt is None:
            return "unknown"
        age = datetime.now() - dt.replace(tzinfo=None)
        if age < timedelta(days=365):
            return "recent"
        if age < timedelta(days=365 * 3):
            return "aging"
        if age < timedelta(days=365 * 5):
            return "stale"
        return "historical"

    @classmethod
    def _resolve_evidence_date(cls, source_date: str, llm_date: str) -> str:
        """Source date wins; fall back to LLM date only when source is empty."""
        return (source_date or "").strip() or (llm_date or "").strip()

    @classmethod
    def _temporal_sort_key(cls, item) -> tuple[int, float]:
        """Sort key: (temporal_level_rank, -overall_confidence)."""
        qs = getattr(item, "quality_score", None) or {}
        if not isinstance(qs, dict):
            qs = {}
        level = qs.get("temporal_level") or cls._compute_temporal_level(
            getattr(item, "date", "")
        )
        rank = cls._TEMPORAL_RANK.get(level, cls._TEMPORAL_RANK["unknown"])
        conf = qs.get("overall_confidence", 0.0)
        if not isinstance(conf, (int, float)):
            conf = 0.0
        return (rank, -float(conf))

    @classmethod
    def _sort_evidence_by_temporal(cls, items: list) -> list:
        """Attach temporal_level into quality_score and sort in place.

        Priority: temporal_level (recent > aging > unknown > stale > historical)
                  then overall_confidence descending.
        """
        for e in items:
            qs = getattr(e, "quality_score", None) or {}
            if not isinstance(qs, dict):
                qs = {}
            if not qs.get("temporal_level"):
                qs["temporal_level"] = cls._compute_temporal_level(
                    getattr(e, "date", "")
                )
            e.quality_score = qs
        items.sort(key=cls._temporal_sort_key)
        return items

    @staticmethod
    def _compute_aggregate_freshness(items: list) -> int | str:
        """Aggregate real freshness_score (0-1) into 0-100; 'unknown' if absent."""
        scores = []
        for e in items:
            qs = getattr(e, "quality_score", None) or {}
            if not isinstance(qs, dict):
                continue
            fs = qs.get("freshness_score")
            if isinstance(fs, (int, float)):
                scores.append(float(fs))
        if not scores:
            return "unknown"
        return round(sum(scores) / len(scores) * 100)

    async def arun(self, ctx: AgentContext, input_data: ResearchInput) -> AgentResult:
        """Execute evidence collection.

        1. Extract research_tasks from Planner's ResearchPlan
        2. Route tasks via SourceRouter → parallel source execution
        3. LLM extract evidence
        4. Build output
        """
        objective = (input_data.research_plan.get("objective", "") if isinstance(input_data.research_plan, dict) else input_data.research_plan.objective) if input_data.research_plan else (
            f"分析 {input_data.competitor_company} 的 {input_data.product}"
        )
        deadline = datetime.utcnow().timestamp() + float(getattr(input_data, "time_budget_seconds", 300.0) or 300.0)
        max_source_types = max(1, int(getattr(input_data, "max_source_types", 3) or 3))
        max_results = max(1, int(getattr(input_data, "max_results_per_source", 5) or 5))
        self._partial_input_data = input_data
        self._partial_evidence_items = []
        self._partial_all_results = []
        self._partial_fallback_meta = {}
        self._partial_task_id = ctx.task_id or ""
        self._last_cap_meta = {}

        def _time_left() -> float:
            return max(0.0, deadline - datetime.utcnow().timestamp())

        try:
            return await self._run_research(ctx, input_data, objective, max_source_types, max_results, _time_left)
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _touch_research_progress(task_id: str, progress: float, stage_hint: str) -> None:
        if not task_id:
            return
        try:
            from app.infrastructure.persistence import task_report_runtime

            task_report_runtime.touch_task_progress(
                task_id,
                current_phase="researching",
                progress=progress,
                current_agent="research",
                stage_hint=stage_hint,
            )
        except Exception:
            pass

    async def _run_research(
        self,
        ctx: AgentContext,
        input_data: ResearchInput,
        objective: str,
        max_source_types: int,
        max_results: int,
        _time_left,
    ) -> AgentResult:
        """Core research flow (separated so CancelledError propagates cleanly)."""
        # Step 1: Build Source Selection Plan (LLM-driven with rule-based fallback)
        if input_data.research_plan and _dget(input_data.research_plan, "analysis_scope", []):
            try:
                router_timeout = min(45.0, max(8.0, _time_left() * 0.25))
                sel_plan = await asyncio.wait_for(
                    llm_router.route(
                        dimensions=_dget(input_data.research_plan, "analysis_scope", []),
                        keywords=source_router._collect_keywords(input_data.research_plan) if input_data.research_plan else [],
                        objective=objective,
                        task_id=ctx.task_id,
                    ),
                    timeout=router_timeout,
                )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("llm_router timed out/failed, using rule fallback: %s", exc)
                sel_plan = source_selection.build_plan(
                    dimensions=_dget(input_data.research_plan, "analysis_scope", []),
                    keywords=source_router._collect_keywords(input_data.research_plan) if input_data.research_plan else [],
                    objective=objective,
                )
        else:
            sel_plan = None

        self._touch_research_progress(
            ctx.task_id,
            24.0,
            RESEARCH_PROGRESS_HINTS[24.0],
        )

        # Step 2: Execute searches via the execution plan
        from app.infrastructure.tools.evidence_freshness import (
            cutoff_iso,
            freshness_query_hint,
        )

        months = int(getattr(input_data, "evidence_max_age_months", 48) or 48)
        context = {
            "task_id": ctx.task_id,
            "objective": objective,
            "our_company": input_data.our_company,
            "competitor_company": input_data.competitor_company,
            "product": input_data.product,
            "max_results_per_source": max_results,
            "evidence_start_date": cutoff_iso(months),
            "freshness_query_hint": freshness_query_hint(months),
            "evidence_max_age_months": months,
        }
        exec_plan = None
        if sel_plan:
            # Build SourceExecutionPlan compatible with execute_plan
            from app.infrastructure.tools.dimension_router import SourceExecutionPlan
            source_types = list(sel_plan.all_source_types or [])
            # Prefer web first, then truncate to mode budget.
            preferred = ["web", "news", "app_store", "social"]
            ordered = [s for s in preferred if s in source_types] + [
                s for s in source_types if s not in preferred
            ]
            source_types = ordered[:max_source_types] or ["web"]
            exec_plan = SourceExecutionPlan(
                dimensions=sel_plan.dimensions,
                source_types=source_types,
                keywords=sel_plan.tasks[0].keywords if sel_plan.tasks else [],
                objective=sel_plan.objective,
                dimension_mapping={t.dimension: t.sources for t in sel_plan.tasks},
            )
            all_results = await source_router.execute_plan(exec_plan, context=context)
        else:
            # Fallback: no research plan, use legacy task-based routing
            all_results = await source_router.search_many([], context=context)

        self._partial_all_results = list(all_results)

        try:
            from app.infrastructure.persistence import task_report_runtime
            task_report_runtime.touch_task_progress(
                ctx.task_id,
                current_phase="researching",
                progress=28.0,
                current_agent="research",
                stage_hint=RESEARCH_PROGRESS_HINTS[28.0],
            )
        except Exception:
            pass

        # Step 3: Extract evidence via LLM (or raw fallback if budget is tight)
        if _time_left() < 25.0:
            self._touch_research_progress(
                ctx.task_id,
                32.0,
                RESEARCH_PROGRESS_HINTS[32.0],
            )
            self._touch_research_progress(
                ctx.task_id,
                36.0,
                RESEARCH_PROGRESS_HINTS[36.0],
            )
            evidence_items = []
            for result in all_results:
                if result.error or not result.items:
                    continue
                evidence_items.extend(
                    self._raw_items_as_evidence(result, max_results, mark_timeout_fallback=True)
                )
            # Deduplicate quickly
            seen: set[str] = set()
            deduped: list[EvidenceItemDTO] = []
            for e in evidence_items:
                if e.url and e.url in seen:
                    continue
                if e.url:
                    seen.add(e.url)
                deduped.append(e)
            for idx, e in enumerate(deduped):
                e.id = f"E{idx + 1:03d}"
            evidence_items, cap_meta = self._apply_evidence_caps(deduped, input_data)
            self._partial_evidence_items = list(evidence_items)
            search_summary = "time_budget_low: used raw search results"
            if cap_meta.get("evidence_truncated_count"):
                search_summary += (
                    f" | evidence truncated to {input_data.max_evidence_items}"
                    " for full mode budget"
                )
        else:
            evidence_items, search_summary = await self._extract_evidence_from_sources(
                objective,
                all_results,
                input_data,
                max_results,
                _time_left,
                task_id=ctx.task_id,
            )

        self._partial_evidence_items = list(evidence_items)

        self._touch_research_progress(
            ctx.task_id,
            40.0,
            RESEARCH_PROGRESS_HINTS[40.0],
        )

        # Step 4: Heuristic date fill + page_meta enrich + age window + build output
        evidence_items = await self._apply_date_and_freshness_pipeline(
            evidence_items, input_data,
        )
        self._partial_evidence_items = list(evidence_items)
        bundle, quality = self._build_output(
            input_data, evidence_items, all_results,
        )

        output = ResearchOutput(
            evidence_bundle=bundle,
            quality_report=quality,
        )
        cap_meta = getattr(self, "_last_cap_meta", {}) or {}
        freshness_meta = getattr(self, "_last_freshness_meta", {}) or {}
        phase_record = {
            "phase": Phase.RESEARCHING.value,
            "duration_ms": 0,
            "status": "completed",
            "selection_plan": sel_plan.dimensions if sel_plan else [],
            "selection_tasks": [t.dimension + ":" + ",".join(t.sources) for t in sel_plan.tasks] if sel_plan else [],
            "source_types_selected": exec_plan.source_types if exec_plan else [],
            "tasks_executed": len(exec_plan.source_types) if exec_plan else 0,
            "sources_called": len(all_results),
            "sources_succeeded": sum(1 for r in all_results if r.status == "success"),
            "total_results": sum(len(r.items) for r in all_results),
            "evidence_count": len(evidence_items),
            "llm_generated": True,
        }
        if cap_meta:
            phase_record.update(cap_meta)
        if freshness_meta:
            phase_record.update(freshness_meta)
        return AgentResult(
            success=True,
            output=output,
            phase_record=phase_record,
        )

    @classmethod
    def _enrich_evidence_dates(cls, items: list[EvidenceItemDTO]) -> None:
        """Heuristic date fill + refresh temporal_level / confidence (deterministic)."""
        from app.infrastructure.tools.evidence_date import enrich_evidence_dates

        enrich_evidence_dates(items)
        for e in items:
            qs = getattr(e, "quality_score", None) or {}
            if not isinstance(qs, dict):
                qs = {}
            else:
                qs = dict(qs)
            qs["temporal_level"] = cls._compute_temporal_level(getattr(e, "date", "") or "")
            raw = getattr(e, "raw_data", None) or {}
            if isinstance(raw, dict) and raw.get("temporal_confidence"):
                qs["temporal_confidence"] = raw["temporal_confidence"]
            elif not qs.get("temporal_confidence"):
                qs["temporal_confidence"] = "low" if not (getattr(e, "date", "") or "") else "medium"
            e.quality_score = qs

    async def _apply_date_and_freshness_pipeline(
        self,
        evidence_items: list[EvidenceItemDTO],
        input_data: ResearchInput,
    ) -> list[EvidenceItemDTO]:
        """Heuristic dates → light page_meta → age window → re-id."""
        from app.infrastructure.tools.evidence_freshness import (
            apply_evidence_age_window,
            enrich_missing_dates_from_page_meta,
        )

        items = list(evidence_items or [])
        self._enrich_evidence_dates(items)

        enrich_stats: dict[str, Any] = {}
        try:
            enrich_stats = await enrich_missing_dates_from_page_meta(
                items,
                enabled=bool(getattr(input_data, "enable_lightweight_date_enrichment", True)),
                max_urls=int(getattr(input_data, "date_enrichment_max_urls", 8) or 8),
                timeout_s=float(getattr(input_data, "date_enrichment_timeout_s", 2.5) or 2.5),
                concurrency=3,
            )
        except Exception as exc:
            logger.debug("page_meta date enrichment skipped: %s", exc)
            enrich_stats = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}

        if int(enrich_stats.get("succeeded") or 0) > 0:
            self._enrich_evidence_dates(items)

        filtered, window_meta = apply_evidence_age_window(
            items,
            max_age_months=int(getattr(input_data, "evidence_max_age_months", 48) or 48),
            max_undated_evidence_items=int(
                getattr(input_data, "max_undated_evidence_items", 5) or 5
            ),
        )
        capped, cap_meta = self._apply_evidence_caps(filtered, input_data)
        for idx, e in enumerate(capped):
            e.id = f"E{idx + 1:03d}"

        prior_cap = getattr(self, "_last_cap_meta", {}) or {}
        merged_cap = {**prior_cap, **(cap_meta or {})}
        self._last_cap_meta = merged_cap
        self._last_freshness_meta = {
            **window_meta,
            "date_enrichment_attempted": int(enrich_stats.get("attempted") or 0),
            "date_enrichment_succeeded": int(enrich_stats.get("succeeded") or 0),
        }
        return capped

    @classmethod
    def _ensure_default_quality_scores(cls, items: list[EvidenceItemDTO]) -> None:
        """Rule-based temporal/score defaults for items not LLM-evaluated."""
        for e in items:
            qs = getattr(e, "quality_score", None) or {}
            if not isinstance(qs, dict):
                qs = {}
            if not qs.get("temporal_level"):
                qs["temporal_level"] = cls._compute_temporal_level(getattr(e, "date", ""))
            if qs.get("overall_confidence") is None:
                qs.setdefault("authority_score", 0.5)
                qs.setdefault("freshness_score", 0.5)
                qs.setdefault("relevance_score", 0.5)
                qs.setdefault("reliability_score", 0.5)
                qs["overall_confidence"] = 0.5
                qs["evaluator_skipped"] = True
            e.quality_score = qs

    def _apply_evidence_caps(
        self,
        items: list[EvidenceItemDTO],
        input_data: ResearchInput,
    ) -> tuple[list[EvidenceItemDTO], dict[str, int]]:
        """Sort, truncate to max_evidence_items (full mode budget)."""
        meta = {"evidence_truncated_count": 0, "evaluator_skipped_count": 0}
        if items:
            self._sort_evidence_by_temporal(items)
        max_ev = getattr(input_data, "max_evidence_items", None)
        if max_ev is not None and max_ev > 0 and len(items) > max_ev:
            meta["evidence_truncated_count"] = len(items) - max_ev
            logger.info(
                "evidence truncated to %d for full mode budget (dropped %d)",
                max_ev,
                meta["evidence_truncated_count"],
            )
            items = items[:max_ev]
        self._last_cap_meta = meta
        return items, meta

    # ── Evidence Extraction from SourceResults ──

    async def _extract_evidence_from_sources(
        self,
        objective: str,
        all_results: list[SourceResult],
        input_data: ResearchInput,
        max_results: int,
        time_left_fn,
        task_id: str = "",
    ) -> tuple[list[EvidenceItemDTO], str]:
        """LLM extracts structured evidence from multi-source search results."""
        self._touch_research_progress(
            task_id,
            32.0,
            RESEARCH_PROGRESS_HINTS[32.0],
        )
        workable = [r for r in all_results if not r.error and r.items]
        all_summaries: list[str] = []
        for result in all_results:
            if result.error:
                all_summaries.append(f"[{result.source_name}] 错误: {result.error}")
            elif not result.items:
                all_summaries.append(f"[{result.source_name}] 无结果")

        sem = asyncio.Semaphore(3)

        async def _extract_one(result: SourceResult) -> list[EvidenceItemDTO]:
            if time_left_fn() < 8.0:
                all_summaries.append(f"[{result.source_name}] 时间预算不足，使用原始结果")
                return self._raw_items_as_evidence(result, max_results)

            source_label = f"{result.source_name} ({result.source_type})"
            items_json = json.dumps([
                {
                    "title": item.title,
                    "url": item.url,
                    "content": (item.content or "")[:800],
                    "published_date": item.published_date,
                    "source_type": item.source_type,
                    "source_name": item.source_name,
                    "metrics": item.metrics,
                }
                for item in result.items[:max_results]
            ], ensure_ascii=False, indent=2)

            extract_wait = min(60.0, max(5.0, time_left_fn() - 2.0))
            llm_wait = min(45.0, max(3.0, extract_wait - 5.0))

            async with sem:
                try:
                    prompt = build_extraction_prompt(source_label, objective, items_json)
                    extraction_result = await asyncio.wait_for(
                        llm_client.generate(
                            system_prompt=SYSTEM_PROMPT,
                            user_prompt=prompt,
                            response_model=ExtractedEvidence,
                            temperature=0.3,
                            timeout=llm_wait,
                        ),
                        timeout=extract_wait,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    all_summaries.append(f"[{result.source_name}] LLM调用失败 ({exc})")
                    return self._raw_items_as_evidence(result, max_results)

                if extraction_result.parsed and extraction_result.parsed.evidence_items:
                    source_date_map: dict[str, str] = {
                        item.url: (getattr(item, "published_date", "") or "")
                        for item in result.items
                        if getattr(item, "url", "") and (getattr(item, "published_date", "") or "")
                    }
                    extracted: list[EvidenceItemDTO] = []
                    for e in extraction_result.parsed.evidence_items:
                        source_date = source_date_map.get(e.url, "") or ""
                        llm_date = e.date or ""
                        final_date = self._resolve_evidence_date(source_date, llm_date)
                        extracted.append(EvidenceItemDTO(
                            title=e.title,
                            source=e.source,
                            source_type=result.source_type,
                            url=e.url,
                            date=final_date,
                            content=e.summary,
                            confidence=e.confidence,
                            category=e.dimension,
                            extracted_at=datetime.utcnow(),
                        ))
                    self._enrich_evidence_dates(extracted)
                    all_summaries.append(
                        f"[{result.source_name}] 从 {len(result.items)} 条结果中提取 {len(extracted)} 条证据"
                    )
                    return extracted

                all_summaries.append(
                    f"[{result.source_name}] LLM解析失败，回退原始 {len(result.items)} 条结果"
                )
                return self._raw_items_as_evidence(result, max_results)

        batches: list[list[EvidenceItemDTO]] = []
        tasks = [asyncio.create_task(_extract_one(r)) for r in workable]
        for finished in asyncio.as_completed(tasks):
            batch = await finished
            batches.append(batch)
            # Early partial snapshot after each source extract completes
            accumulated = [e for b in batches for e in b]
            self._partial_evidence_items = list(accumulated)

        all_evidence = [e for batch in batches for e in batch]

        # Deduplicate by URL and assign stable 1-based evidence IDs (E001, E002, ...)
        seen_urls: set[str] = set()
        deduped: list[EvidenceItemDTO] = []
        for e in all_evidence:
            if e.url and e.url not in seen_urls:
                seen_urls.add(e.url)
                deduped.append(e)
            elif not e.url:
                deduped.append(e)
        for idx, e in enumerate(deduped):
            e.id = f"E{idx + 1:03d}"

        self._partial_evidence_items = list(deduped)
        search_summary = " | ".join(all_summaries) if all_summaries else "无搜索执行"

        skip_eval = bool(getattr(input_data, "skip_evidence_evaluation", False))
        eval_budget = time_left_fn()
        max_eval = getattr(input_data, "max_evaluated_items", None)
        evaluator_skipped_count = 0

        if deduped:
            self._sort_evidence_by_temporal(deduped)
            self._ensure_default_quality_scores(deduped)

        eval_items = deduped
        if max_eval is not None and max_eval > 0 and len(deduped) > max_eval:
            eval_items = deduped[:max_eval]
            evaluator_skipped_count = len(deduped) - max_eval

        self._touch_research_progress(
            task_id,
            36.0,
            RESEARCH_PROGRESS_HINTS[36.0],
        )

        if deduped and not skip_eval and eval_budget >= 20.0 and eval_items:
            eval_timeout = min(90.0, max(5.0, eval_budget - 5.0))
            try:
                from app.infrastructure.tools.evidence_evaluator import evidence_evaluator
                score_inputs = [
                    {
                        "id": e.id or "",
                        "title": e.title,
                        "content": e.content,
                        "source_type": e.source_type,
                        "url": e.url,
                        "date": e.date,
                    }
                    for e in eval_items
                ]
                quality_scores = await asyncio.wait_for(
                    evidence_evaluator.evaluate_batch(
                        items=score_inputs,
                        objective=objective,
                        max_concurrent=5,
                    ),
                    timeout=eval_timeout,
                )
                for i, score in enumerate(quality_scores):
                    qs = score.to_dict()
                    qs["evaluator_skipped"] = False
                    deduped[i].quality_score = qs
                    overall = score.overall_confidence
                    if overall >= 0.80:
                        deduped[i].confidence = "high"
                    elif overall >= 0.50:
                        deduped[i].confidence = "medium"
                    elif overall >= 0.30:
                        deduped[i].confidence = "low"
                    else:
                        deduped[i].confidence = "estimated"
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # Evaluator failure is non-blocking
        elif deduped and skip_eval:
            search_summary = f"{search_summary} | evidence_evaluation_skipped"

        deduped, cap_meta = self._apply_evidence_caps(deduped, input_data)
        cap_meta["evaluator_skipped_count"] = evaluator_skipped_count
        self._last_cap_meta = cap_meta
        if cap_meta.get("evidence_truncated_count"):
            max_ev = getattr(input_data, "max_evidence_items", None)
            search_summary = (
                f"{search_summary} | evidence truncated to {max_ev} for full mode budget"
            )

        return deduped, search_summary

    @staticmethod
    def _raw_items_as_evidence(
        result: SourceResult,
        max_results: int = 8,
        *,
        mark_timeout_fallback: bool = False,
    ) -> list[EvidenceItemDTO]:
        """Fallback: keep searchable URLs when LLM extraction fails or times out."""
        dims = [
            "growth",
            "business",
            "users",
            "competitive_landscape",
            "features",
            "positioning",
        ]
        items: list[EvidenceItemDTO] = []
        for i, item in enumerate(result.items[:max_results]):
            if not item.url:
                continue
            snippet = (getattr(item, "content", None) or "")[:500]
            raw_data: dict[str, Any] | None = None
            quality_score: dict[str, Any] | None = None
            confidence = "medium"
            if mark_timeout_fallback:
                confidence = "low"
                raw_data = {
                    "extraction_method": "raw_timeout_fallback",
                    "reliability": "low",
                }
                quality_score = {
                    "authority_score": 0.3,
                    "freshness_score": 0.4,
                    "relevance_score": 0.4,
                    "reliability_score": 0.3,
                    "overall_confidence": 0.3,
                    "extraction_method": "raw_timeout_fallback",
                    "evaluator_skipped": True,
                }
            items.append(EvidenceItemDTO(
                title=item.title or item.url,
                source=item.source_name or result.source_name,
                source_type=result.source_type or getattr(item, "source_type", "") or "web",
                url=item.url,
                date=getattr(item, "published_date", "") or "",
                content=snippet,
                confidence=confidence,
                category=dims[i % len(dims)],
                extracted_at=datetime.utcnow(),
                raw_data=raw_data,
                quality_score=quality_score,
            ))
        # Enrich after build so URL/snippet dates fill empty published_date
        ResearchAgent._enrich_evidence_dates(items)
        return items

    def _convert_raw_results_to_evidence(
        self,
        all_results: list[SourceResult],
        input_data: ResearchInput,
        *,
        mark_timeout_fallback: bool = True,
        exclude_urls: set[str] | None = None,
    ) -> tuple[list[EvidenceItemDTO], int]:
        """Convert successful raw SourceResult items into capped evidence DTOs."""
        exclude = exclude_urls or set()
        max_results = max(1, int(getattr(input_data, "max_results_per_source", 5) or 5))
        collected: list[EvidenceItemDTO] = []
        for result in all_results:
            if result.error or not result.items:
                continue
            for e in self._raw_items_as_evidence(
                result, max_results, mark_timeout_fallback=mark_timeout_fallback,
            ):
                if e.url and e.url in exclude:
                    continue
                collected.append(e)

        seen: set[str] = set()
        deduped: list[EvidenceItemDTO] = []
        for e in collected:
            if e.url and e.url in seen:
                continue
            if e.url:
                seen.add(e.url)
            deduped.append(e)

        for idx, e in enumerate(deduped):
            if not e.id:
                e.id = f"E{idx + 1:03d}"

        capped, _ = self._apply_evidence_caps(deduped, input_data)
        # Re-id after cap for stable E001.. numbering
        for idx, e in enumerate(capped):
            e.id = f"E{idx + 1:03d}"
        return capped, len(capped)

    def _top_up_evidence_with_raw(
        self,
        evidence_items: list[EvidenceItemDTO],
        all_results: list[SourceResult],
        input_data: ResearchInput,
    ) -> tuple[list[EvidenceItemDTO], int]:
        """Keep extracted evidence; fill remaining cap slots from unused raw URLs."""
        max_ev = getattr(input_data, "max_evidence_items", None)
        if max_ev is not None and max_ev > 0 and len(evidence_items) >= max_ev:
            return evidence_items, 0

        existing_urls = {e.url for e in evidence_items if e.url}
        raw_extra, _ = self._convert_raw_results_to_evidence(
            all_results,
            input_data,
            mark_timeout_fallback=True,
            exclude_urls=existing_urls,
        )
        if not raw_extra:
            return evidence_items, 0

        merged = list(evidence_items) + raw_extra
        # Re-assign ids after merge, then cap
        for idx, e in enumerate(merged):
            e.id = f"E{idx + 1:03d}"
        capped, _ = self._apply_evidence_caps(merged, input_data)
        for idx, e in enumerate(capped):
            e.id = f"E{idx + 1:03d}"
        added = max(0, len(capped) - len(evidence_items))
        return capped, added

    # ── Step 4: Build Output ──

    def _build_output(
        self,
        input_data: ResearchInput,
        evidence_items: list[EvidenceItemDTO],
        all_results: list[SourceResult],
    ) -> tuple[EvidenceBundleDTO, QualityReport]:
        """Build EvidenceBundle and QualityReport from extracted evidence."""
        total_results = sum(len(r.items) for r in all_results)
        sources_used: list[dict] = []
        for e in evidence_items:
            domain = ""
            if e.url:
                from urllib.parse import urlparse
                domain = urlparse(e.url).netloc
            sources_used.append({
                # source_id 与证据 id（E001/E002...）对齐，报告引用 [E001] 可直接匹配
                "source_id": e.id or f"src_{len(sources_used):03d}",
                "domain": domain,
                "url": e.url,
                "title": e.title,
                "summary": (e.content or "")[:300],
                "source_type": e.source_type,
                "date": e.date,
            })

        # Build company/product info from top evidence
        our_items = [
            e for e in evidence_items
            if input_data.our_company.lower() in (e.title + e.content).lower()
        ]
        comp_items = [
            e for e in evidence_items
            if input_data.competitor_company.lower() in (e.title + e.content).lower()
        ]

        bundle = EvidenceBundleDTO(
            our_company=CompanyInfoDTO(
                name=input_data.our_company,
                description=self._join_evidence(our_items[:3]),
                data_quality="medium" if our_items else "no_data",
            ),
            competitor_company=CompanyInfoDTO(
                name=input_data.competitor_company,
                description=self._join_evidence(comp_items[:3]),
                data_quality="medium" if comp_items else "no_data",
            ),
            our_product=ProductInfoDTO(
                name=input_data.product,
                description=self._join_evidence(our_items[:2]),
                data_quality="medium" if our_items else "no_data",
            ),
            competitor_product=ProductInfoDTO(
                name=input_data.product,
                description=self._join_evidence(comp_items[:2]),
                data_quality="medium" if comp_items else "no_data",
            ),
            evidence_items=evidence_items,
            news=[],
            reviews=[],
            market=[],
            sources_used=sources_used,
            references=[
                {"url": e.url, "title": e.title} for e in evidence_items if e.url
            ],
            quality_score={
                "overall": min(100, len(evidence_items) * 10),
                "coverage": min(100, len(sources_used) * 10),
                "freshness": self._compute_aggregate_freshness(evidence_items),
                **{
                    k: v
                    for k, v in (getattr(self, "_last_freshness_meta", {}) or {}).items()
                    if k in (
                        "evidence_cutoff_date",
                        "filtered_expired_count",
                        "undated_kept_count",
                        "undated_dropped_count",
                        "date_enrichment_attempted",
                        "date_enrichment_succeeded",
                    )
                },
            },
        )

        # Calculate dimension coverage
        dimensions: dict[str, int] = {}
        for e in evidence_items:
            dim = e.category or "other"
            dimensions[dim] = dimensions.get(dim, 0) + 1
        coverage_by_dimension: dict[str, float] = {}
        for dim, count in dimensions.items():
            coverage_by_dimension[dim] = min(100.0, count * 20.0)

        # Average confidence
        conf_weights = {"high": 1.0, "medium": 0.6, "low": 0.3, "estimated": 0.1}
        avg_conf = (
            sum(conf_weights.get(e.confidence, 0.3) for e in evidence_items)
            / max(len(evidence_items), 1)
        )

        # Count no_api_key sources for warning message
        no_key_count = sum(1 for r in all_results if r.status == "no_api_key")

        freshness_meta = getattr(self, "_last_freshness_meta", {}) or {}
        quality = QualityReport(
            sources_attempted=max(len(all_results), 1),
            sources_succeeded=sum(1 for r in all_results if r.status == "success"),
            total_evidence_items=len(evidence_items),
            coverage_by_dimension=coverage_by_dimension,
            avg_confidence=round(avg_conf, 2),
            fallback_used=False,
            missing_data_warnings=(
                ["未配置任何搜索源 API Key (TAVILY_API_KEY)，无法执行真实搜索"]
                if not evidence_items and no_key_count > 0
                else []
            ),
            filtered_expired_count=int(freshness_meta.get("filtered_expired_count") or 0),
            undated_kept_count=int(freshness_meta.get("undated_kept_count") or 0),
            undated_dropped_count=int(freshness_meta.get("undated_dropped_count") or 0),
            evidence_cutoff_date=str(freshness_meta.get("evidence_cutoff_date") or ""),
            date_enrichment_attempted=int(freshness_meta.get("date_enrichment_attempted") or 0),
            date_enrichment_succeeded=int(freshness_meta.get("date_enrichment_succeeded") or 0),
        )
        cap_meta = getattr(self, "_last_cap_meta", {}) or {}
        if cap_meta.get("evidence_truncated_count"):
            quality.missing_data_warnings = list(quality.missing_data_warnings) + [
                f"evidence truncated to {len(evidence_items)} for full mode budget",
            ]

        return bundle, quality

    @staticmethod
    def _join_evidence(items: list[EvidenceItemDTO]) -> str:
        if not items:
            return ""
        return " | ".join(
            e.content[:200] for e in items if e.content
        )
