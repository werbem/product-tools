"""Multi-step combo detection for Decision Planner (Phase 6).

Combinations are expressed as PlanStep chains — not Router priority hacks.
Uses explicit chain connectors so nested「收集竞品分析报告相关资料」stays single-step.
"""

from __future__ import annotations

import re
from typing import Literal

from app.application.services.decision_intent_signals import looks_like_advice_follow_up
from app.application.services.intent_entities import looks_like_competitor_listing_query
from app.application.services.intent_mapper import (
    detect_analysis_intent,
    detect_collection_intent,
)

MultiStepCombo = Literal[
    "listing_then_analyze",
    "collect_then_advise",
    "collect_then_analyze",
]

# 「收集…并做竞品分析 / 先收集再出分析报告」— not「收集竞品分析报告相关资料」
_COLLECT_THEN_ANALYZE = re.compile(
    r"(?:收集|搜集|调研).{0,48}"
    r"(?:并|再|然后|之后|接着)"
    r".{0,16}"
    r"(?:做|完成|出|写|生成)?"
    r"(?:一份)?"
    r"(?:竞品分析|竞争分析|对比分析|分析报告|完整报告)",
    re.IGNORECASE,
)

# 「收集…并给出运营建议 / 收集完…下一步该怎么做」
_COLLECT_THEN_ADVISE = re.compile(
    r"(?:收集|搜集|调研).{0,56}"
    r"(?:并|再|然后|之后|接着|完(?:之后)?|后)"
    r".{0,24}"
    r"(?:"
    r"给出.{0,12}建议|给(?:我|我们)?.{0,8}建议|提供.{0,12}建议|"
    r"运营建议|产品建议|行动建议|落地建议|"
    r"下一步|该怎么做|应该做什么|应该怎么做|怎么推进"
    r")",
    re.IGNORECASE,
)

# Nested materials object — stay single-step research
_NESTED_CA_MATERIALS = re.compile(
    r"(?:收集|搜集|调研).{0,24}"
    r"(?:竞品分析|分析报告).{0,16}"
    r"(?:相关)?(?:资料|信息|情报)",
)


def detect_multi_step_combo(message: str | None) -> MultiStepCombo | None:
    """Return combo id when the user ask clearly chains two jobs."""
    text = (message or "").strip()
    if not text or len(text) < 8:
        return None

    listing = looks_like_competitor_listing_query(text)
    analysis = detect_analysis_intent(text)
    collection = detect_collection_intent(text)

    # 「有哪些竞品？帮我完成竞品分析报告」
    if listing and analysis:
        return "listing_then_analyze"

    # Nested「收集竞品分析报告相关资料」→ not multi-step
    if _NESTED_CA_MATERIALS.search(text):
        return None

    # 「收集…并做竞品分析」
    if collection and _COLLECT_THEN_ANALYZE.search(text):
        return "collect_then_analyze"

    # 「收集…并给出运营建议 / 下一步」
    if collection and (
        _COLLECT_THEN_ADVISE.search(text)
        or (looks_like_advice_follow_up(text) and not _COLLECT_THEN_ANALYZE.search(text))
    ):
        # Avoid treating bare collect+「给出建议」analysis-signal as deep-only
        if _COLLECT_THEN_ANALYZE.search(text):
            return "collect_then_analyze"
        return "collect_then_advise"

    return None
