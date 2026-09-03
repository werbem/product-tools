"""Strategy Agent — LLM-powered strategic analysis.

Generates SWOT, opportunities, risks, recommendations, roadmap
from evidence + gap analysis using real LLM.
"""

from __future__ import annotations

import json
import re

from app.application.dto.agent_dto import (
    OpportunityItem, RecommendationItem, RiskItem,
    StrategicInsights, StrategyInput, StrategyOutput,
    SWOT, SWOTItem, RoadmapPhase,
)
from app.config.constants import Phase
from app.infrastructure.agents.base import AgentContext, AgentResult, BaseAgent
from app.infrastructure.agents.strategy_prompt import (
    SYSTEM_PROMPT, LLMStrategyOutput, build_strategy_prompt,
    _normalize_strategy_output,
)
from app.infrastructure.llm.client import llm_client

_CONFIDENCE_WEIGHTS = {"high": 1.0, "medium": 0.6, "low": 0.3, "estimated": 0.1}
_TEMPORAL_TIERS = ["recent", "aging", "stale", "historical", "unknown"]

def _dget(obj, key, default=None):
    """Safe dict/object access — handles both Pydantic models and plain dicts."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _aggregate_temporal_levels(levels: list[str]) -> str:
    """Aggregate temporal levels via 70% dominance rule."""
    dist = {t: 0 for t in _TEMPORAL_TIERS}
    for lvl in levels:
        if lvl not in dist:
            lvl = "unknown"
        dist[lvl] += 1
    total = sum(dist.values())
    if total == 0:
        return "unknown"
    for t in _TEMPORAL_TIERS:
        if dist[t] / total >= 0.70:
            return t
    return "mixed"


class StrategyAgent(BaseAgent[StrategyInput, StrategyOutput]):

    def __init__(self) -> None:
        self._partial_input: StrategyInput | None = None
        self._partial_raw_text: str = ""

    @property
    def agent_name(self) -> str:
        return "strategy"

    @property
    def phase(self) -> Phase:
        return Phase.STRATEGIZING

    def build_partial_result(self) -> AgentResult:
        """Timeout fallback: parse partial LLM JSON, else evidence stub."""
        from app.infrastructure.agents.timeout_stubs import (
            build_strategy_stub_from_evidence,
            try_parse_strategy_llm_json,
        )

        input_data = self._partial_input
        eb = getattr(input_data, "evidence_bundle", {}) if input_data else {}
        gap = getattr(input_data, "gap_analysis", {}) if input_data else {}
        product = getattr(input_data, "product", "") if input_data else ""
        objective = getattr(input_data, "objective", "") if input_data else ""
        our = getattr(input_data, "our_company", "") if input_data else ""
        comp = getattr(input_data, "competitor_company", "") if input_data else ""

        parsed = try_parse_strategy_llm_json(self._partial_raw_text)
        if parsed is not None:
            insights = self._insights_from_parsed(
                parsed,
                evidence_items=_dget(eb, "evidence_items", []) or [],
                cluster_temporal_map={},
                evidence_temporal_map={},
                avg_conf=0.5,
            )
            si_dict = insights.model_dump()
            si_dict.update({
                "strategy_timeout": True,
                "strategy_partial": True,
                "strategy_fallback": "partial_json",
                "swot_source": "partial_json",
                "generation_note": "战略结果来自超时前的部分 LLM 输出",
            })
            return AgentResult(
                success=True,
                output=StrategyOutput(
                    strategic_insights=insights,
                    confidence_summary={
                        "sufficient": True,
                        "partial_on_timeout": True,
                        "overall": "medium",
                    },
                ),
                phase_record={
                    "phase": Phase.STRATEGIZING.value,
                    "status": "completed",
                    "error": "strategy_partial_on_timeout",
                    "strategy_timeout": True,
                    "strategy_partial": True,
                    "strategy_fallback": "partial_json",
                    "swot_source": "partial_json",
                    "strategy_dict": si_dict,
                },
            )

        si_dict = build_strategy_stub_from_evidence(
            eb,
            gap_analysis=gap,
            our_company=our,
            competitor_company=comp,
            product=product,
            objective=objective,
        )
        meta_keys = {
            "strategy_timeout", "strategy_fallback", "swot_source",
            "generation_note", "stub_evidence_count", "strategy_partial",
        }
        body = {k: v for k, v in si_dict.items() if k not in meta_keys}
        insights = StrategicInsights(**{
            k: body[k] for k in StrategicInsights.model_fields if k in body
        })
        return AgentResult(
            success=True,
            output=StrategyOutput(
                strategic_insights=insights,
                confidence_summary={
                    "sufficient": bool(_dget(eb, "evidence_items", [])),
                    "evidence_stub": True,
                    "overall": "low",
                },
            ),
            phase_record={
                "phase": Phase.STRATEGIZING.value,
                "status": "completed",
                "error": "strategy_stub_on_timeout",
                "strategy_timeout": True,
                "strategy_fallback": "evidence_stub",
                "swot_source": "evidence_stub",
                "strategy_dict": si_dict,
            },
        )

    def _insights_from_parsed(
        self,
        parsed,
        *,
        evidence_items: list,
        cluster_temporal_map: dict[str, str],
        evidence_temporal_map: dict[str, str],
        avg_conf: float,
    ) -> StrategicInsights:
        swot = SWOT(
            strengths=[SWOTItem(item=s.conclusion, evidence_refs=s.evidence_refs, cluster_refs=getattr(s, "cluster_refs", []) or [], confidence=s.confidence)
                       for s in parsed.swot.strengths],
            weaknesses=[SWOTItem(item=w.conclusion, evidence_refs=w.evidence_refs, cluster_refs=getattr(w, "cluster_refs", []) or [], confidence=w.confidence)
                        for w in parsed.swot.weaknesses],
            opportunities=[SWOTItem(item=o.conclusion, evidence_refs=o.evidence_refs, cluster_refs=getattr(o, "cluster_refs", []) or [], confidence=o.confidence)
                          for o in parsed.swot.opportunities],
            threats=[SWOTItem(item=t.conclusion, evidence_refs=t.evidence_refs, cluster_refs=getattr(t, "cluster_refs", []) or [], confidence=t.confidence)
                    for t in parsed.swot.threats],
        )
        opportunities = [
            OpportunityItem(
                title=o.title, description=o.description,
                impact=o.impact, effort=o.effort,
                alignment_with_objective=o.alignment_with_objective,
                evidence_refs=o.evidence_refs, confidence=o.confidence,
            ) for o in parsed.opportunities
        ]
        risks = [
            RiskItem(title=r.title, description=r.description,
                     probability=r.probability, impact=r.impact,
                     mitigation=r.mitigation, evidence_refs=r.evidence_refs)
            for r in parsed.risks
        ]
        recommendations = []
        for r in parsed.recommendations:
            cluster_refs = getattr(r, "cluster_refs", []) or []
            evidence_refs = r.evidence_refs or []
            evidence_temporal_level = self._resolve_recommendation_temporal(
                cluster_refs,
                evidence_refs,
                cluster_temporal_map,
                evidence_temporal_map,
            )
            rationale = self._apply_temporal_guard(r.rationale, evidence_temporal_level)
            recommendations.append(RecommendationItem(
                action=r.action, rationale=rationale,
                expected_value=r.expected_value, priority=r.priority,
                timeline=r.timeline, evidence_refs=evidence_refs,
                cluster_refs=cluster_refs, kpi=r.kpi or None,
                evidence_temporal_level=evidence_temporal_level,
            ))
        roadmap_obj = getattr(parsed, "roadmap", None)
        if roadmap_obj is not None and hasattr(roadmap_obj, "short_term"):
            roadmap = {
                "phases": [
                    RoadmapPhase(phase="Phase 1 (0-3月)", duration="3个月",
                        initiatives=[a.action for a in roadmap_obj.short_term],
                        success_criteria=["行动启动率 > 80%"]).model_dump(),
                    RoadmapPhase(phase="Phase 2 (3-6月)", duration="3个月",
                        initiatives=[a.action for a in roadmap_obj.medium_term],
                        success_criteria=["关键指标改善 20%"]).model_dump(),
                    RoadmapPhase(phase="Phase 3 (6-12月)", duration="6个月",
                        initiatives=[a.action for a in roadmap_obj.long_term],
                        success_criteria=["能力差距缩小 50%"]).model_dump(),
                ]
            }
        else:
            roadmap = {"phases": []}
        return StrategicInsights(
            swot=swot, opportunities=opportunities, risks=risks,
            recommendations=recommendations, roadmap=roadmap,
            confidence_labels={
                "overall": getattr(parsed, "overall_confidence", "medium") or "medium",
                "swot": "high" if len(swot.strengths) >= 2 else "medium",
                "opportunities": "medium" if len(opportunities) >= 2 else "low",
                "risks": "medium",
                "recommendations": "medium",
                "evidence_quality": f"{avg_conf:.0%}",
            },
        )

    @staticmethod
    def _build_insight_temporal_maps(
        insights: list,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Map cluster/evidence id -> insight.evidence_temporal_level."""
        cluster_map: dict[str, str] = {}
        evidence_map: dict[str, str] = {}
        for ins in insights:
            if isinstance(ins, dict):
                etl = ins.get("evidence_temporal_level", "unknown") or "unknown"
                cluster_refs = ins.get("cluster_refs", []) or []
                evidence_refs = ins.get("evidence_refs", []) or []
            else:
                etl = getattr(ins, "evidence_temporal_level", "unknown") or "unknown"
                cluster_refs = getattr(ins, "cluster_refs", []) or []
                evidence_refs = getattr(ins, "evidence_refs", []) or []
            for cr in cluster_refs:
                cluster_map[str(cr)] = etl
            for er in evidence_refs:
                evidence_map[str(er)] = etl
        return cluster_map, evidence_map

    @staticmethod
    def _resolve_recommendation_temporal(
        cluster_refs: list[str],
        evidence_refs: list[str],
        cluster_map: dict[str, str],
        evidence_map: dict[str, str],
    ) -> str:
        """Inherit temporal from referenced insights (cluster first, evidence fallback)."""
        if cluster_refs:
            levels = [cluster_map.get(str(cr)) for cr in cluster_refs if cluster_map.get(str(cr))]
            if levels:
                return _aggregate_temporal_levels(levels)
        levels = [evidence_map.get(str(er)) for er in evidence_refs if evidence_map.get(str(er))]
        if levels:
            return _aggregate_temporal_levels(levels)
        return "unknown"

    @staticmethod
    def _apply_temporal_guard(rationale: str, temporal_level: str) -> str:
        """Append a low-timeliness hint for historical/stale recommendations."""
        if temporal_level in ("historical", "stale"):
            hint = "该建议主要基于低时效数据，需要近期数据验证"
            return (rationale + " " if rationale else "") + hint
        return rationale

    async def arun(self, ctx: AgentContext, input_data: StrategyInput) -> AgentResult:
        import time

        from app.infrastructure.agents.agent_io_compact import (
            COMPACT_EVIDENCE_CAP,
            COMPACT_SNIPPET_CHARS,
            compress_evidence_items,
        )
        from app.infrastructure.agents.strategy_prompt import (
            COMPACT_STRATEGY_SYSTEM,
            build_strategy_prompt_compact,
            build_strategy_repair_prompt,
        )
        from app.infrastructure.agents.timeout_stubs import try_parse_strategy_llm_json
        from app.infrastructure.workflow.workflow_budget import split_primary_repair_timeouts

        self._partial_input = input_data
        self._partial_raw_text = ""
        t0 = time.monotonic()
        eb = input_data.evidence_bundle
        gap = input_data.gap_analysis
        compact = bool(getattr(input_data, "compact", True))
        research_incomplete = bool(getattr(input_data, "research_incomplete", False))

        evidence_items = _dget(eb, "evidence_items", []) or []
        if not evidence_items:
            if not (input_data.insights or []):
                return self._need_more("没有收集到任何证据")
        dims = {}
        for e in evidence_items:
            cat = _dget(e, "category", "unknown")
            dims[cat or "unknown"] = dims.get(cat or "unknown", 0) + 1
        dims_enough = sum(1 for v in dims.values() if v >= 2)
        scores = [_CONFIDENCE_WEIGHTS.get(_dget(e, "confidence", "estimated"), 0.3) for e in evidence_items]
        avg_conf = (sum(scores) / len(scores)) if scores else 0.0
        quality_warnings: list[str] = []
        if evidence_items and dims_enough < 2 and len(evidence_items) < 3:
            quality_warnings.append(
                f"证据覆盖偏窄（有效维度 {dims_enough}），战略建议置信度下调"
            )
        if evidence_items and avg_conf < 0.2:
            quality_warnings.append(f"证据可信度偏低 (avg={avg_conf:.0%})")

        gap_summary = self._summarize_gap(gap)
        if compact:
            packed = compress_evidence_items(
                evidence_items, cap=COMPACT_EVIDENCE_CAP, snippet_chars=COMPACT_SNIPPET_CHARS,
            )
            evidence_json = json.dumps(packed, ensure_ascii=False)
            insights_list = (input_data.insights or [])[:6]
            insights_json = json.dumps(insights_list, ensure_ascii=False)
            user_prompt = build_strategy_prompt_compact(
                objective=input_data.objective,
                product=input_data.product,
                gap_summary=gap_summary,
                evidence_json=evidence_json,
                insights_json=insights_json,
                research_incomplete=research_incomplete,
                memory_notes_context=getattr(input_data, "memory_notes_context", None),
            )
            system_prompt = COMPACT_STRATEGY_SYSTEM
            use_schema = False
        else:
            evidence_json = json.dumps([
                {
                    "id": _dget(e, "id", ""), "title": _dget(e, "title", ""),
                    "source": _dget(e, "source", ""), "url": _dget(e, "url", ""),
                    "dimension": _dget(e, "category", ""),
                    "summary": (_dget(e, "content", "") or "")[:250],
                    "confidence": _dget(e, "confidence", "estimated"),
                }
                for e in sorted(
                    evidence_items,
                    key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(
                        _dget(x, "confidence", "estimated"), 3,
                    ),
                )[:15]
            ], ensure_ascii=False, indent=2)
            insights_list = input_data.insights or []
            insights_json = json.dumps(insights_list, ensure_ascii=False, indent=2)
            user_prompt = build_strategy_prompt(
                objective=input_data.objective,
                product=input_data.product,
                gap_summary=gap_summary,
                evidence_json=evidence_json,
                insights_json=insights_json,
                memory_notes_context=getattr(input_data, "memory_notes_context", None),
            )
            system_prompt = SYSTEM_PROMPT
            use_schema = True

        cluster_temporal_map, evidence_temporal_map = self._build_insight_temporal_maps(
            input_data.insights or [],
        )
        node_timeout = float(input_data.llm_timeout_seconds or 90.0)
        primary_t, repair_t = split_primary_repair_timeouts(node_timeout)

        parsed = None
        try:
            gen_kwargs: dict = {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "response_model": LLMStrategyOutput if use_schema else None,
                "temperature": 0.3 if compact else 0.5,
            }
            if primary_t > 0:
                gen_kwargs["timeout"] = primary_t
            result = await llm_client.generate(**gen_kwargs)
            self._partial_raw_text = (result.content or "").strip()
            parsed = result.parsed if isinstance(result.parsed, LLMStrategyOutput) else None
            if parsed is None:
                parsed = try_parse_strategy_llm_json(self._partial_raw_text)
        except Exception:
            parsed = None

        if parsed is None and repair_t >= 8.0:
            try:
                repair = await llm_client.generate(
                    system_prompt=COMPACT_STRATEGY_SYSTEM if compact else SYSTEM_PROMPT,
                    user_prompt=build_strategy_repair_prompt(
                        self._partial_raw_text or user_prompt[-1500:],
                    ),
                    response_model=None,
                    temperature=0.1,
                    timeout=repair_t,
                )
                self._partial_raw_text = (repair.content or "").strip()
                parsed = try_parse_strategy_llm_json(self._partial_raw_text)
            except Exception:
                parsed = None

        elapsed = round(time.monotonic() - t0, 2)
        if not parsed:
            out = self._need_more("LLM 返回格式异常")
            pr = dict(out.phase_record or {})
            pr.update({
                "strategy_mode": "parse_fail",
                "strategy_elapsed_s": elapsed,
            })
            out.phase_record = pr
            return out

        insights = self._insights_from_parsed(
            parsed,
            evidence_items=evidence_items,
            cluster_temporal_map=cluster_temporal_map,
            evidence_temporal_map=evidence_temporal_map,
            avg_conf=avg_conf,
        )
        if quality_warnings:
            labels = dict(insights.confidence_labels or {})
            labels["warnings"] = "; ".join(quality_warnings)
            insights = StrategicInsights(
                swot=insights.swot,
                opportunities=insights.opportunities,
                risks=insights.risks,
                recommendations=insights.recommendations,
                roadmap=insights.roadmap,
                confidence_labels=labels,
            )

        output = StrategyOutput(
            strategic_insights=insights,
            confidence_summary={
                "sufficient": True,
                "overall": insights.confidence_labels.get("overall", "medium"),
                "evidence_quality": avg_conf,
                "evidence_counts": dims,
                "total_items": len(evidence_items),
                "warnings": quality_warnings,
            },
        )
        return AgentResult(
            success=True,
            output=output,
            phase_record={
                "phase": Phase.STRATEGIZING.value,
                "status": "completed",
                "llm_generated": True,
                "strategy_mode": "compact_agent" if compact else "full_agent",
                "strategy_elapsed_s": elapsed,
            },
        )

    def _need_more(self, reason: str) -> AgentResult:
        output = StrategyOutput(
            strategic_insights=StrategicInsights(
                swot=SWOT(), opportunities=[], risks=[],
                recommendations=[], roadmap={"phases": []},
                confidence_labels={},
            ),
            confidence_summary={
                "sufficient": False,
                "message": f"Need More Research: {reason}",
                "weaknesses": [reason],
                "data_gaps": [reason],
            },
        )
        return AgentResult(success=True, output=output)

    @staticmethod
    def _summarize_gap(gap) -> str:
        fm = _dget(gap, "features", {})
        if isinstance(fm, dict):
            fm = fm.get("feature_matrix", [])
        else:
            fm = _dget(fm, "feature_matrix", []) if fm else []
        gaps = _dget(gap, "gaps", {}) or {}
        pos = _dget(gap, "positioning", {}) or {}
        caps = gaps.get("capability_gaps", [])
        advs = gaps.get("competitive_advantages", [])
        disadvs = gaps.get("competitive_disadvantages", [])

        parts = []
        if pos:
            parts.append(f"定位差异: {pos.get('positioning_diff', '')}")
        if fm:
            parts.append(f"差异点({len(fm)}项): " + "; ".join(
                f.get("feature_name", "")[:60] for f in fm[:5]))
        if advs:
            parts.append(f"优势: " + "; ".join(
                a.get("description", "")[:80] for a in advs[:3]))
        if disadvs:
            parts.append(f"劣势: " + "; ".join(
                d.get("description", "")[:80] for d in disadvs[:3]))
        if caps:
            parts.append(f"能力差距: " + "; ".join(
                c.get("description", "")[:100] for c in caps[:3]))
        return "\n".join(parts) if parts else "差距分析为空"
