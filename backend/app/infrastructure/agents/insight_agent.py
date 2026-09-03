"""Insight Agent — Fact/Observation/Hypothesis from EvidenceClusters + GapAnalysis.

Flow:
  1. Receive EvidenceClusters + Compare GapAnalysis
  2. LLM generates structured insights (Fact/Observation/Hypothesis)
  3. Each insight references cluster + evidence

Rules:
  - No evidence = no insight (never fabricate)
  - Fact must have direct evidence_refs
  - Hypothesis must be clearly labeled + confidence scored
"""

from __future__ import annotations

import json
import re

from app.application.dto.agent_dto import (
    InsightInput, InsightOutput, ProductInsight,
)
from app.config.constants import Phase
from app.infrastructure.agents.base import AgentContext, AgentResult, BaseAgent
from app.infrastructure.agents.insight_prompt import (
    SYSTEM_PROMPT, build_insight_prompt, LLMInsightOutput,
)
from app.infrastructure.llm.client import llm_client


_TEMPORAL_TIERS = ["recent", "aging", "stale", "historical", "unknown"]
_CONFIDENCE_DOWNGRADE = {
    "high": "medium",
    "medium": "low",
    "low": "low",
    "estimated": "estimated",
}


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


class InsightAgent(BaseAgent[InsightInput, InsightOutput]):

    @property
    def agent_name(self) -> str:
        return "insight"

    @property
    def phase(self) -> Phase:
        return Phase.INSIGHTING

    @staticmethod
    def _build_temporal_maps(
        clusters: list,
        gaps: dict,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Map cluster id -> temporal_level and evidence id -> gap temporal_level."""
        cluster_map: dict[str, str] = {}
        for c in clusters:
            if isinstance(c, dict):
                cid = c.get("cluster_id", "")
                level = c.get("temporal_level", "unknown") or "unknown"
            else:
                cid = getattr(c, "cluster_id", "")
                level = getattr(c, "temporal_level", "unknown") or "unknown"
            if cid:
                cluster_map[str(cid)] = level

        gap_evidence_map: dict[str, str] = {}
        gaps_inner = (gaps or {}).get("gaps", {}) if isinstance(gaps, dict) else {}
        capability_gaps = gaps_inner.get("capability_gaps", []) if isinstance(gaps_inner, dict) else []
        for gap in capability_gaps:
            if not isinstance(gap, dict):
                continue
            etl = gap.get("evidence_temporal_level", "unknown") or "unknown"
            for er in gap.get("evidence_refs", []) or []:
                gap_evidence_map[str(er)] = etl

        return cluster_map, gap_evidence_map

    @staticmethod
    def _resolve_insight_temporal(
        cluster_refs: list[str],
        evidence_refs: list[str],
        cluster_map: dict[str, str],
        gap_evidence_map: dict[str, str],
    ) -> str:
        """Compute insight evidence_temporal_level (cluster first, gap fallback)."""
        if cluster_refs:
            levels = [cluster_map.get(str(cr)) for cr in cluster_refs if cluster_map.get(str(cr))]
            if levels:
                return _aggregate_temporal_levels(levels)
        levels = [gap_evidence_map.get(str(er)) for er in evidence_refs if gap_evidence_map.get(str(er))]
        if levels:
            return _aggregate_temporal_levels(levels)
        return "unknown"

    @staticmethod
    def _apply_temporal_guard(
        insight_type: str,
        confidence: str,
        impact: str,
        temporal_level: str,
        description: str,
    ) -> tuple[str, str]:
        """Apply temporal guard: adjust confidence + append risk hint."""
        new_confidence = confidence
        hint = ""
        if temporal_level in ("historical", "stale"):
            if insight_type == "hypothesis":
                new_confidence = "low"
            elif insight_type == "observation":
                new_confidence = _CONFIDENCE_DOWNGRADE.get(confidence, "low")
            # fact: keep confidence
            hint = "该洞察主要基于低时效数据，需要近期数据验证"
            if impact == "high":
                hint += "；该洞察影响等级高，需谨慎采纳"
        if hint:
            description = (description + " " if description else "") + hint
        return new_confidence, description

    @staticmethod
    def _apply_quality_gate(
        insight_type: str,
        confidence: str,
        evidence_refs: list[str],
        cluster_refs: list[str],
        description: str,
    ) -> tuple[bool, str, str]:
        """Rule-based quality gate for insights.

        Returns (keep, confidence, description).
        - BLOCK: fact/hypothesis with zero evidence (hallucination).
        - WARN: hypothesis backed by a single evidence reference (weak chain).
        """
        evidence_count = len(evidence_refs or []) + len(cluster_refs or [])

        # Rule 1 & 2: fact/hypothesis without any evidence → block
        if insight_type in ("fact", "hypothesis") and evidence_count == 0:
            return (False, confidence, description)

        # Rule 3: weak hypothesis (fewer than 2 references) → warn
        if insight_type == "hypothesis" and evidence_count < 2:
            new_confidence = _CONFIDENCE_DOWNGRADE.get(confidence, "low")
            hint = "该假设基于有限证据，需要进一步验证"
            new_description = (description + " " if description else "") + hint
            return (True, new_confidence, new_description)

        return (True, confidence, description)

    async def arun(self, ctx: AgentContext, input_data: InsightInput) -> AgentResult:
        clusters = input_data.evidence_clusters or []
        gaps = input_data.gap_analysis or {}
        flat_items = list(input_data.flat_evidence_items or [])
        cluster_map, gap_evidence_map = self._build_temporal_maps(clusters, gaps)

        has_caps = bool((gaps.get("gaps") or {}).get("capability_gaps", [])) if isinstance(gaps, dict) else False
        use_flat = False
        if not clusters and not has_caps:
            if not flat_items:
                return AgentResult(success=True, output=InsightOutput(
                    insights=[], summary="证据不足，无法生成洞察",
                ), phase_record={
                    "phase": "insighting",
                    "status": "no_data",
                    "insight_skipped_empty_gap": True,
                    "insight_flat_evidence": False,
                })
            use_flat = True

        objective = input_data.objective or (
            f"分析 {input_data.competitor_company} 的 {input_data.product}"
        )
        gaps_json = json.dumps(gaps, ensure_ascii=False, indent=2)
        if use_flat:
            from app.infrastructure.agents.insight_prompt import build_flat_insight_prompt
            evidence_json = json.dumps([
                {
                    "id": (e.get("id") if isinstance(e, dict) else getattr(e, "id", "")),
                    "title": (e.get("title") if isinstance(e, dict) else getattr(e, "title", "")),
                    "summary": ((e.get("content") if isinstance(e, dict) else getattr(e, "content", "")) or "")[:250],
                    "confidence": (e.get("confidence") if isinstance(e, dict) else getattr(e, "confidence", "medium")),
                }
                for e in flat_items[:12]
            ], ensure_ascii=False, indent=2)
            user_prompt = build_flat_insight_prompt(
                our_company=input_data.our_company,
                competitor_company=input_data.competitor_company,
                product=input_data.product,
                objective=objective,
                evidence_json=evidence_json,
                gaps_json=gaps_json,
            )
        else:
            clusters_json = json.dumps(clusters, ensure_ascii=False, indent=2)
            user_prompt = build_insight_prompt(
                our_company=input_data.our_company,
                competitor_company=input_data.competitor_company,
                product=input_data.product,
                objective=objective,
                clusters_json=clusters_json,
                gaps_json=gaps_json,
            )

        try:
            gen_kwargs: dict = {
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": user_prompt,
                "response_model": None,
                "temperature": 0.4,
            }
            if input_data.llm_timeout_seconds is not None:
                gen_kwargs["timeout"] = input_data.llm_timeout_seconds
            result = await llm_client.generate(**gen_kwargs)
        except Exception:
            return AgentResult(success=False, output=InsightOutput(),
                error="LLM调用失败",
                phase_record={"phase": "insighting", "status": "llm_error"})

        parsed = self._parse_insights(result.content or "")

        if not parsed or not parsed.insights:
            return AgentResult(success=True, output=InsightOutput(
                insights=[], summary="LLM未生成洞察",
            ), phase_record={
                "phase": "insighting",
                "status": "completed",
                "insight_count": 0,
                "insight_flat_evidence": use_flat,
                "insight_skipped_empty_gap": False,
            })

        insights = []
        for item in parsed.insights:
            evidence_temporal_level = self._resolve_insight_temporal(
                item.cluster_refs,
                item.evidence_refs,
                cluster_map,
                gap_evidence_map,
            )
            confidence, description = self._apply_temporal_guard(
                item.type,
                item.confidence,
                item.impact,
                evidence_temporal_level,
                item.description,
            )
            keep, confidence, description = self._apply_quality_gate(
                item.type,
                confidence,
                item.evidence_refs,
                item.cluster_refs,
                description,
            )
            if not keep:
                continue
            insights.append(ProductInsight(
                title=item.title,
                type=item.type,
                description=description,
                evidence_refs=item.evidence_refs,
                cluster_refs=item.cluster_refs,
                confidence=confidence,
                impact=item.impact,
                dimension=item.dimension,
                evidence_temporal_level=evidence_temporal_level,
            ))

        facts = sum(1 for i in insights if i.type == "fact")
        obs = sum(1 for i in insights if i.type == "observation")
        hyps = sum(1 for i in insights if i.type == "hypothesis")

        return AgentResult(success=True, output=InsightOutput(
            insights=insights,
            fact_count=facts,
            observation_count=obs,
            hypothesis_count=hyps,
            summary=parsed.summary,
        ), phase_record={
            "phase": "insighting", "status": "completed",
            "insight_count": len(insights),
            "fact_count": facts, "observation_count": obs, "hypothesis_count": hyps,
            "insight_flat_evidence": use_flat,
            "insight_skipped_empty_gap": False,
        })

    @staticmethod
    def _parse_insights(raw: str):
        """Parse LLM JSON response."""
        raw = raw.strip()

        # Strip ```json fences
        code_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if code_match:
            raw = code_match.group(1).strip()

        try:
            data = json.loads(raw)
            return LLMInsightOutput(
                insights=[InsightAgent._norm_item(i) for i in data.get("insights", [])],
                summary=data.get("summary", ""),
            )
        except (json.JSONDecodeError, Exception):
            pass

        # Fallback: regex extract JSON
        json_match = re.search(r'\{.*"insights".*\}', raw, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                return LLMInsightOutput(
                    insights=[InsightAgent._norm_item(i) for i in data.get("insights", [])],
                    summary=data.get("summary", ""),
                )
            except (json.JSONDecodeError, Exception):
                pass

        return None

    @staticmethod
    def _norm_item(item: dict):
        from app.infrastructure.agents.insight_prompt import InsightItem
        if isinstance(item, str):
            return InsightItem(title=item[:100], type="fact")
        return InsightItem(**{
            k: v for k, v in item.items()
            if k in InsightItem.model_fields
        })


# ── Singleton ──
insight_agent = InsightAgent()
