"""Map IntentUnderstandingResult to ReportCreateRequest + workflow routing."""

from __future__ import annotations

import re
from typing import Any, Literal

from app.application.dto.intent_dto import KNOWN_OBJECTIVES, IntentUnderstandingResult
from app.application.dto.report_dto import ReportCreateRequest

WorkflowKind = Literal["deep_analysis", "intelligence_collection"]

# A. Deep-analysis strong signals
_ANALYSIS_SIGNAL_PATTERN = re.compile(
    r"竞品分析|竞争分析|对比分析|分析报告|完整报告|战略建议|给出建议|差异分析|竞品差异|"
    r"给出.{0,12}建议|产品策略建议|"
    r"对比(?!研究)|分析.{0,40}(?:vs|VS|竞品)|(?:vs|VS).{0,40}分析|"
    r"competitive\s+analysis|competitor\s+analysis|comparison\s+report|"
    r"strategy\s+recommendation",
    re.IGNORECASE,
)

# B. Collection strong signals — no bare「商业行为」/「市场信息」
_COLLECTION_SIGNAL_PATTERN = re.compile(
    r"帮我收集|搜集一下|信息收集|资料汇总|收集|情报|调研|近期动态|近期信息|资料",
)

# Soft keywords only count when co-occurring with collection verbs
_SOFT_COLLECTION_COOC_PATTERN = re.compile(
    r"(?:收集|调研|搜集|整理).{0,24}(?:商业行为|市场信息)"
    r"|(?:商业行为|市场信息).{0,24}(?:收集|调研|搜集|资料|信息)",
)

_FOCUS_CLAUSE_PATTERN = re.compile(
    r"(?:重点(?:是|：|:)|focus(?:ing)?\s+on)\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_INTEL_COLLECTION_DIMENSIONS = [
    "商业发展与市场动态",
    "增长与运营策略",
    "商业模式与变现",
]


def detect_analysis_intent(text: str | None) -> bool:
    return bool(_ANALYSIS_SIGNAL_PATTERN.search(text or ""))


def detect_collection_intent(text: str | None) -> bool:
    """True when message looks like intelligence collection (not bare 商业行为)."""
    text = text or ""
    if _SOFT_COLLECTION_COOC_PATTERN.search(text):
        return True
    return bool(_COLLECTION_SIGNAL_PATTERN.search(text))


def matched_analysis_signals(text: str | None) -> list[str]:
    return [m.group(0) for m in _ANALYSIS_SIGNAL_PATTERN.finditer(text or "")]


def matched_collection_signals(text: str | None) -> list[str]:
    text = text or ""
    hits = [m.group(0) for m in _COLLECTION_SIGNAL_PATTERN.finditer(text)]
    soft = [m.group(0) for m in _SOFT_COLLECTION_COOC_PATTERN.finditer(text)]
    # de-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for h in hits + soft:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def resolve_workflow_kind(
    intent: IntentUnderstandingResult,
    text: str | None = None,
) -> WorkflowKind:
    """Priority: analysis(+competitors / both signals) > collection > default deep."""
    raw = text if text is not None else (intent.raw_message or "")
    has_analysis = detect_analysis_intent(raw)
    has_collection = detect_collection_intent(raw) or (
        (intent.objective or "") == "intelligence_collection"
    )
    competitors = [c for c in (intent.competitors or []) if c]

    # 3) both → analysis wins
    if has_analysis and has_collection:
        return "deep_analysis"
    # 1) analysis strong signal + competitors
    if has_analysis and competitors:
        return "deep_analysis"
    # Explicit analysis ask without competitors still prefers deep path
    # (clarification / mapper will require competitors for launch)
    if has_analysis:
        return "deep_analysis"
    # 2 / 4) collection without analysis
    if has_collection:
        return "intelligence_collection"
    return "deep_analysis"


def build_routing_debug(
    intent: IntentUnderstandingResult,
    text: str | None = None,
) -> dict[str, Any]:
    raw = text if text is not None else (intent.raw_message or "")
    kind = resolve_workflow_kind(intent, raw)
    has_analysis = detect_analysis_intent(raw)
    has_collection = detect_collection_intent(raw)
    matched_a = matched_analysis_signals(raw)
    matched_c = matched_collection_signals(raw)

    if has_analysis and has_collection:
        reason = "analysis_signal_overrides_collection_keyword"
    elif has_analysis and (intent.competitors or []):
        reason = "analysis_signal_with_competitors"
    elif has_analysis:
        reason = "analysis_signal"
    elif has_collection:
        reason = "collection_signal"
    elif (intent.objective or "") == "intelligence_collection":
        reason = "objective_intelligence_collection"
    else:
        reason = "default_deep_analysis"

    return {
        "routing_reason": reason,
        "workflow_kind": kind,
        "matched_analysis": matched_a,
        "matched_collection": matched_c,
    }


def is_intelligence_collection(intent: IntentUnderstandingResult) -> bool:
    return resolve_workflow_kind(intent) == "intelligence_collection"


def _extract_focus_scene(raw_message: str) -> str | None:
    m = _FOCUS_CLAUSE_PATTERN.search((raw_message or "").strip())
    if not m:
        return None
    focus = (m.group(1) or "").strip().rstrip("。．.！!？?")
    return focus or None


def to_report_create_request(
    intent: IntentUnderstandingResult,
    analysis_mode: str = "fast",
) -> ReportCreateRequest:
    if intent.type != "competitive_analysis":
        raise ValueError("intent type must be competitive_analysis")
    if intent.needs_clarification:
        raise ValueError("intent needs clarification")
    if not intent.company:
        raise ValueError("company is required")
    if not intent.product:
        raise ValueError("product is required")

    kind = resolve_workflow_kind(intent)
    routing_debug = build_routing_debug(intent)

    if intent.competitors:
        competitor_company = "、".join(intent.competitors)
    elif kind == "intelligence_collection":
        competitor_company = "公开市场与主要竞品"
    else:
        raise ValueError("competitors are required")

    objective = intent.objective
    scene = None

    if not objective:
        objective = "product_improvement"
    elif objective == "intelligence_collection":
        # Keep user wording as analysis focus when redirected to deep_analysis
        scene = _extract_focus_scene(intent.raw_message) or intent.raw_message
        objective = "product_improvement"
    elif objective not in KNOWN_OBJECTIVES:
        scene = objective
        objective = "product_improvement"

    if kind == "deep_analysis" and not scene:
        scene = _extract_focus_scene(intent.raw_message)

    return ReportCreateRequest(
        our_company=intent.company,
        competitor_company=competitor_company,
        product=intent.product,
        objective=objective,
        scene=scene,
        optional={
            "source": "intent_understanding",
            "raw_message": intent.raw_message,
            "competitors": intent.competitors,
            "analysis_mode": analysis_mode,
            "workflow_kind": kind,
            "routing_debug": routing_debug,
            **(
                {
                    "dimensions": list(_INTEL_COLLECTION_DIMENSIONS),
                    "skip_evidence_evaluation": True,
                }
                if kind == "intelligence_collection"
                else {}
            ),
        },
    )
