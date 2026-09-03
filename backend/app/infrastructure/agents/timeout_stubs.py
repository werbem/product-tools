"""Compare / Strategy timeout degradation: partial JSON parse + evidence stubs.

Aligned with Research Step 34 philosophy — never silently return {}.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.application.dto.agent_dto import (
    GapAnalysis,
    GapItem,
    RecommendationItem,
    SWOT,
    SWOTItem,
    StrategicInsights,
)
from app.infrastructure.agents.compare_prompt import _normalize_llm_output
from app.infrastructure.agents.strategy_prompt import _normalize_strategy_output

COMPARE_EVIDENCE_STUB_CAP = 12
COMPARE_GENERATION_NOTE = "对比结果由证据摘要生成，非完整 Compare Agent 输出"
STRATEGY_GENERATION_NOTE = "战略结果由证据摘要生成，非完整 Strategy Agent 输出"


def _dget(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _get_temporal_level(item: Any) -> str:
    qs = _dget(item, "quality_score", None) or {}
    if isinstance(qs, dict):
        return qs.get("temporal_level", "") or ""
    return getattr(qs, "temporal_level", "") or ""


def _items_from_bundle(evidence_bundle: Any, *, cap: int = COMPARE_EVIDENCE_STUB_CAP) -> list:
    raw = _dget(evidence_bundle, "evidence_items", []) or []
    return list(raw)[:cap]


def try_parse_compare_llm_json(raw_text: str) -> Any | None:
    """Return normalized LLMCompareOutput if JSON is usable; else None."""
    text = (raw_text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        if not isinstance(data, dict):
            return None
        if not (data.get("differences") or data.get("capability_gaps")):
            return None
        return _normalize_llm_output(data)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def try_parse_strategy_llm_json(raw_text: str) -> Any | None:
    """Return normalized strategy output if SWOT or recommendations present."""
    text = (raw_text or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return None
        data = json.loads(m.group())
        if not isinstance(data, dict):
            return None
        parsed = _normalize_strategy_output(data)
        swot = getattr(parsed, "swot", None)
        has_swot = bool(
            swot
            and (
                getattr(swot, "strengths", None)
                or getattr(swot, "weaknesses", None)
                or getattr(swot, "opportunities", None)
                or getattr(swot, "threats", None)
            )
        )
        has_recs = bool(getattr(parsed, "recommendations", None))
        if has_swot or has_recs:
            return parsed
        return None
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return None


def build_compare_stub_from_evidence(
    evidence_bundle: Any,
    *,
    our_company: str = "",
    competitor_company: str = "",
    product: str = "",
) -> dict[str, Any]:
    """Minimal gap_analysis from evidence summaries (never a bare {})."""
    items = _items_from_bundle(evidence_bundle)
    feature_matrix: list[dict[str, Any]] = []
    capability_gaps: list[dict[str, Any]] = []
    refs: list[str] = []

    for e in items:
        eid = str(_dget(e, "id", "") or "")
        title = str(_dget(e, "title", "") or eid or "证据")
        summary = (str(_dget(e, "content", "") or "")).strip()[:200]
        category = str(_dget(e, "category", "") or "general")
        temporal = _get_temporal_level(e) or "unknown"
        if eid:
            refs.append(eid)
        er = [eid] if eid else []
        feature_matrix.append({
            "category": category,
            "feature_name": title[:80],
            "our_coverage": "see_evidence",
            "competitor_coverage": "see_evidence",
            "differentiator": False,
            "evidence_refs": er,
            "cluster_refs": [],
        })
        capability_gaps.append(
            GapItem(
                dimension=category,
                description=f"[证据摘要] {title}: {summary}" if summary else f"[证据摘要] {title}",
                evidence_refs=er,
                impact="medium",
                evidence_temporal_level=temporal,
            ).model_dump()
        )

    our = our_company or "我方"
    comp = competitor_company or "竞品"
    prod = product or "产品"
    positioning = {
        "our_positioning": f"{our} / {prod}（证据摘要，待完整对比）",
        "competitor_positioning": f"{comp} / {prod}（证据摘要，待完整对比）",
        "positioning_diff": COMPARE_GENERATION_NOTE if items else "无可用证据",
    }

    gap = GapAnalysis(
        positioning=positioning if items else {},
        features={
            "feature_matrix": feature_matrix,
            "unique_our_features": [],
            "unique_competitor_features": [],
            "overall_summary": COMPARE_GENERATION_NOTE if items else "无可用证据，无法生成对比摘要",
        },
        gaps={
            "competitive_advantages": [],
            "competitive_disadvantages": [],
            "capability_gaps": capability_gaps,
        },
        evidence_references=sorted(set(refs)),
    )
    out = gap.model_dump()
    out.update({
        "compare_timeout": True,
        "compare_fallback": "evidence_stub",
        "generation_note": COMPARE_GENERATION_NOTE,
        "stub_evidence_count": len(items),
    })
    return out


def build_strategy_stub_from_evidence(
    evidence_bundle: Any,
    *,
    gap_analysis: Any = None,
    our_company: str = "",
    competitor_company: str = "",
    product: str = "",
    objective: str = "",
) -> dict[str, Any]:
    """Minimal SWOT + 2–3 recommendations from evidence (never silent {})."""
    items = _items_from_bundle(evidence_bundle, cap=12)
    our = our_company or "我方"
    comp = competitor_company or "竞品"

    strengths: list[SWOTItem] = []
    weaknesses: list[SWOTItem] = []
    opportunities: list[SWOTItem] = []
    threats: list[SWOTItem] = []

    for e in items:
        eid = str(_dget(e, "id", "") or "")
        title = str(_dget(e, "title", "") or eid or "证据")
        summary = (str(_dget(e, "content", "") or "")).strip()[:160]
        er = [eid] if eid else []
        blob = f"{title} {summary}"
        entry = SWOTItem(
            item=f"[证据] {title}" + (f"：{summary}" if summary else ""),
            evidence_refs=er,
            confidence="low",
        )
        if our and our in blob and len(strengths) < 3:
            strengths.append(entry)
        elif comp and any(p.strip() and p.strip() in blob for p in comp.replace("、", ",").split(",")) and len(threats) < 3:
            threats.append(entry)
        elif len(weaknesses) < 2:
            weaknesses.append(entry)
        elif len(opportunities) < 2:
            opportunities.append(entry)
        elif len(strengths) < 3:
            strengths.append(entry)
        else:
            threats.append(entry)

    if items and not strengths:
        e0 = items[0]
        strengths.append(SWOTItem(
            item=f"[证据] {(_dget(e0, 'title', '') or '公开信息')}",
            evidence_refs=[str(_dget(e0, "id", ""))] if _dget(e0, "id", "") else [],
            confidence="low",
        ))

    # Prefer gap stub capability_gaps as weaknesses if SWOT still thin
    gaps = _dget(gap_analysis, "gaps", {}) or {}
    if isinstance(gaps, dict):
        for g in (gaps.get("capability_gaps") or [])[:2]:
            desc = _dget(g, "description", "") if not isinstance(g, dict) else g.get("description", "")
            refs = _dget(g, "evidence_refs", []) if not isinstance(g, dict) else g.get("evidence_refs", [])
            if desc and len(weaknesses) < 3:
                weaknesses.append(SWOTItem(
                    item=str(desc)[:200],
                    evidence_refs=list(refs or []),
                    confidence="low",
                ))

    recommendations: list[RecommendationItem] = []
    for e in items[:3]:
        eid = str(_dget(e, "id", "") or "")
        title = str(_dget(e, "title", "") or eid or "相关证据")
        recommendations.append(RecommendationItem(
            action=f"围绕「{title[:60]}」做证据核验与产品动作设计",
            rationale=f"Strategy 超时，基于证据摘要提出的参考方向（目标：{objective or '竞品分析'}）",
            priority="p2",
            timeline="short_term",
            evidence_refs=[eid] if eid else [],
            expected_value="待完整 Strategy 验证",
        ))

    if not items:
        recommendations = [
            RecommendationItem(
                action="补充公开证据后重新执行战略分析",
                rationale="无可用证据，无法生成 SWOT/建议 stub",
                priority="p0",
                timeline="immediate",
                evidence_refs=[],
            )
        ]

    insights = StrategicInsights(
        swot=SWOT(
            strengths=strengths,
            weaknesses=weaknesses,
            opportunities=opportunities,
            threats=threats,
        ),
        opportunities=[],
        risks=[],
        recommendations=recommendations,
        roadmap={"phases": []},
        confidence_labels={
            "overall": "low",
            "swot": "evidence_stub",
            "source": "evidence_stub",
        },
    )
    out = insights.model_dump()
    out.update({
        "strategy_timeout": True,
        "strategy_fallback": "evidence_stub",
        "swot_source": "evidence_stub",
        "generation_note": STRATEGY_GENERATION_NOTE,
        "stub_evidence_count": len(items),
    })
    return out


def gap_dict_has_substance(gap: Any) -> bool:
    if not gap or not isinstance(gap, dict):
        return False
    features = gap.get("features") or {}
    fm = features.get("feature_matrix") if isinstance(features, dict) else []
    gaps = gap.get("gaps") or {}
    caps = gaps.get("capability_gaps") if isinstance(gaps, dict) else []
    return bool(fm or caps or gap.get("evidence_references") or gap.get("positioning"))


def strategy_dict_has_substance(si: Any) -> bool:
    if not si or not isinstance(si, dict):
        return False
    swot = si.get("swot") or {}
    if isinstance(swot, dict):
        for k in ("strengths", "weaknesses", "opportunities", "threats"):
            if swot.get(k):
                return True
    return bool(si.get("recommendations"))
