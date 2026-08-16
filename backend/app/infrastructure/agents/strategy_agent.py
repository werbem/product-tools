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

    @property
    def agent_name(self) -> str:
        return "strategy"

    @property
    def phase(self) -> Phase:
        return Phase.STRATEGIZING

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
        eb = input_data.evidence_bundle
        gap = input_data.gap_analysis

        # ── Step 1: Assess evidence quality (rule-based, keeps gate logic) ──
        evidence_items = _dget(eb, "evidence_items", [])
        if not evidence_items:
            return self._need_more("没有收集到任何证据")
        dims = {}
        for e in evidence_items:
            cat = _dget(e, "category", "unknown")
            dims[cat or "unknown"] = dims.get(cat or "unknown", 0) + 1
        dims_enough = sum(1 for v in dims.values() if v >= 2)
        if dims_enough < 2:
            return self._need_more(f"证据覆盖不足，仅 {dims_enough} 个维度有足够数据")

        scores = [_CONFIDENCE_WEIGHTS.get(_dget(e, "confidence", "estimated"), 0.3) for e in evidence_items]
        avg_conf = sum(scores) / len(scores)
        if avg_conf < 0.2:
            return self._need_more(f"证据可信度过低 (avg={avg_conf:.0%})")

        # ── Step 2: Build gap summary ──
        gap_summary = self._summarize_gap(gap)

        # ── Step 3: Build evidence JSON ──
        evidence_json = json.dumps([
            {"id": _dget(e, "id", ""), "title": _dget(e, "title", ""), "source": _dget(e, "source", ""), "url": _dget(e, "url", ""),
             "dimension": _dget(e, "category", ""), "summary": (_dget(e, "content", "") or "")[:250], "confidence": _dget(e, "confidence", "estimated")}
            for e in sorted(evidence_items, key=lambda x: {"high":0,"medium":1,"low":2}.get(_dget(x, "confidence", "estimated"),3))[:15]
        ], ensure_ascii=False, indent=2)

        # ── Step 3.5: Build insights JSON ──
        insights_list = input_data.insights or []
        insights_json = json.dumps(insights_list, ensure_ascii=False, indent=2)
        cluster_temporal_map, evidence_temporal_map = self._build_insight_temporal_maps(insights_list)

        # ── Step 4: Call LLM ──
        try:
            result = await llm_client.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=build_strategy_prompt(
                    objective=input_data.objective,
                    product=input_data.product,
                    gap_summary=gap_summary,
                    evidence_json=evidence_json,
                    insights_json=insights_json,
                ),
                response_model=LLMStrategyOutput,
                temperature=0.5,
                timeout=900.0,
            )
        except Exception:
            return self._need_more("LLM 调用失败")

        # ── Step 5: Parse JSON directly ──
        parsed = result.parsed if isinstance(result.parsed, LLMStrategyOutput) else None
        if parsed is None:
            # Fallback: parse raw content directly
            raw_text = (result.content or "").strip()
            if raw_text:
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("\n", 1)[-1].rsplit("```", 1)[0]
                try:
                    m = re.search(r"\{.*\}", raw_text, re.DOTALL)
                    if m:
                        data = json.loads(m.group())
                        if isinstance(data, dict):
                            parsed = _normalize_strategy_output(data)
                except (json.JSONDecodeError, Exception):
                    parsed = None

        if not parsed:
            return self._need_more("LLM 返回格式异常")

        # ── Step 6: Map to existing DTOs ──
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

        roadmap = {
            "phases": [
                RoadmapPhase(phase="Phase 1 (0-3月)", duration="3个月",
                    initiatives=[a.action for a in parsed.roadmap.short_term],
                    success_criteria=["行动启动率 > 80%"]).model_dump(),
                RoadmapPhase(phase="Phase 2 (3-6月)", duration="3个月",
                    initiatives=[a.action for a in parsed.roadmap.medium_term],
                    success_criteria=["关键指标改善 20%"]).model_dump(),
                RoadmapPhase(phase="Phase 3 (6-12月)", duration="6个月",
                    initiatives=[a.action for a in parsed.roadmap.long_term],
                    success_criteria=["能力差距缩小 50%"]).model_dump(),
            ]
        }

        insights = StrategicInsights(
            swot=swot, opportunities=opportunities, risks=risks,
            recommendations=recommendations, roadmap=roadmap,
            confidence_labels={
                "overall": parsed.overall_confidence,
                "swot": "high" if len(swot.strengths) >= 2 else "medium",
                "opportunities": "medium" if len(opportunities) >= 2 else "low",
                "risks": "medium",
                "recommendations": "medium",
                "evidence_quality": f"{avg_conf:.0%}",
            },
        )

        output = StrategyOutput(
            strategic_insights=insights,
            confidence_summary={
                "sufficient": True, "overall": parsed.overall_confidence,
                "evidence_quality": avg_conf,
                "evidence_counts": dims, "total_items": len(evidence_items),
            },
        )
        return AgentResult(success=True, output=output)

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
