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

        # Step 1: Build Source Selection Plan (LLM-driven with rule-based fallback)
        if input_data.research_plan and _dget(input_data.research_plan, "analysis_scope", []):
            sel_plan = await llm_router.route(
                dimensions=_dget(input_data.research_plan, "analysis_scope", []),
                keywords=source_router._collect_keywords(input_data.research_plan) if input_data.research_plan else [],
                objective=objective,
                task_id=ctx.task_id,
            )
        else:
            sel_plan = None

        # Step 2: Execute searches via the execution plan
        context = {
            "task_id": ctx.task_id,
            "objective": objective,
            "our_company": input_data.our_company,
            "competitor_company": input_data.competitor_company,
            "product": input_data.product,
        }
        if sel_plan:
            # Build SourceExecutionPlan compatible with execute_plan
            from app.infrastructure.tools.dimension_router import SourceExecutionPlan
            exec_plan = SourceExecutionPlan(
                dimensions=sel_plan.dimensions,
                source_types=sel_plan.all_source_types,
                keywords=sel_plan.tasks[0].keywords if sel_plan.tasks else [],
                objective=sel_plan.objective,
                dimension_mapping={t.dimension: t.sources for t in sel_plan.tasks},
            )
            all_results = await source_router.execute_plan(exec_plan, context=context)
        else:
            # Fallback: no research plan, use legacy task-based routing
            all_results = await source_router.search_many([], context=context)

        # Step 3: Extract evidence via LLM (uses raw items from SourceResults)
        evidence_items, search_summary = await self._extract_evidence_from_sources(
            objective, all_results,
        )

        # Step 4: Build output
        bundle, quality = self._build_output(
            input_data, evidence_items, all_results,
        )

        output = ResearchOutput(
            evidence_bundle=bundle,
            quality_report=quality,
        )
        return AgentResult(
            success=True,
            output=output,
            phase_record={
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
            },
        )

    # ── Evidence Extraction from SourceResults ──

    async def _extract_evidence_from_sources(
        self,
        objective: str,
        all_results: list[SourceResult],
    ) -> tuple[list[EvidenceItemDTO], str]:
        """LLM extracts structured evidence from multi-source search results."""
        all_evidence: list[EvidenceItemDTO] = []
        all_summaries: list[str] = []

        for result in all_results:
            if result.error:
                all_summaries.append(
                    f"[{result.source_name}] 错误: {result.error}"
                )
                continue

            if not result.items:
                all_summaries.append(f"[{result.source_name}] 无结果")
                continue

            # Build query label for the LLM prompt
            source_label = f"{result.source_name} ({result.source_type})"

            # Serialize items for LLM extraction
            items_json = json.dumps([
                {
                    "title": item.title,
                    "url": item.url,
                    "content": item.content[:1500],
                    "published_date": item.published_date,
                    "source_type": item.source_type,
                    "source_name": item.source_name,
                    "metrics": item.metrics,
                }
                for item in result.items[:10]
            ], ensure_ascii=False, indent=2)

            try:
                prompt = build_extraction_prompt(source_label, objective, items_json)
                extraction_result = await llm_client.generate(
                    system_prompt=SYSTEM_PROMPT,
                    user_prompt=prompt,
                    response_model=ExtractedEvidence,
                    temperature=0.3,
                )

                if extraction_result.parsed and extraction_result.parsed.evidence_items:
                    # Source published_date takes priority over LLM date.
                    # Map url -> source date so LLM cannot overwrite a real date.
                    source_date_map: dict[str, str] = {
                        item.url: (getattr(item, "published_date", "") or "")
                        for item in result.items
                        if getattr(item, "url", "") and (getattr(item, "published_date", "") or "")
                    }
                    for e in extraction_result.parsed.evidence_items:
                        source_date = source_date_map.get(e.url, "") or ""
                        llm_date = e.date or ""
                        final_date = self._resolve_evidence_date(source_date, llm_date)
                        logger.info(
                            "Evidence date resolution url=%s source_date=%r llm_date=%r final_date=%r",
                            e.url, source_date, llm_date, final_date,
                        )
                        all_evidence.append(EvidenceItemDTO(
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
                    all_summaries.append(
                        f"[{result.source_name}] 从 {len(result.items)} 条结果中提取 {len(extraction_result.parsed.evidence_items)} 条证据"
                    )
                else:
                    all_summaries.append(
                        f"[{result.source_name}] LLM解析失败，返回 {len(result.items)} 条原始结果"
                    )
            except Exception as exc:
                all_summaries.append(
                    f"[{result.source_name}] LLM调用失败 ({exc})"
                )

        # Deduplicate by URL and assign stable 1-based evidence IDs (E001, E002, ...)
        seen_urls: set[str] = set()
        deduped: list[EvidenceItemDTO] = []
        for e in all_evidence:
            if e.url and e.url not in seen_urls:
                seen_urls.add(e.url)
                deduped.append(e)
            elif not e.url:
                # Keep items without URL (shouldn't happen, but safety)
                deduped.append(e)
        for idx, e in enumerate(deduped):
            e.id = f"E{idx + 1:03d}"

        search_summary = " | ".join(all_summaries) if all_summaries else "无搜索执行"

        # Evaluate evidence quality (NEW: Evidence Intelligence Layer)
        if deduped:
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
                    for e in deduped
                ]
                quality_scores = await evidence_evaluator.evaluate_batch(
                    items=score_inputs,
                    objective=objective,
                    max_concurrent=10,
                )
                for i, score in enumerate(quality_scores):
                    deduped[i].quality_score = score.to_dict()
                    # Also update confidence string based on overall score
                    overall = score.overall_confidence
                    if overall >= 0.80:
                        deduped[i].confidence = "high"
                    elif overall >= 0.50:
                        deduped[i].confidence = "medium"
                    elif overall >= 0.30:
                        deduped[i].confidence = "low"
                    else:
                        deduped[i].confidence = "estimated"
            except Exception:
                pass  # Evaluator failure is non-blocking

        # Sort by temporal level (then overall confidence) so recent evidence
        # is prioritized into the report's core citations, and old data
        # (historical) is demoted out of the top slots.
        if deduped:
            self._sort_evidence_by_temporal(deduped)

        return deduped, search_summary

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
        )

        return bundle, quality

    @staticmethod
    def _join_evidence(items: list[EvidenceItemDTO]) -> str:
        if not items:
            return ""
        return " | ".join(
            e.content[:200] for e in items if e.content
        )
