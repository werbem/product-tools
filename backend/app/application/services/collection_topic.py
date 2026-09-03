"""Resolve user-facing collection topic (zh/en), never expose raw enum codes."""

from __future__ import annotations

import re
from typing import Any

from app.config.constants import AnalysisObjective

# CJK Unified Ideographs + Hiragana/Katakana + Hangul
_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\uac00-\ud7af]"
)

OBJECTIVE_LABELS_ZH: dict[str, str] = {
    AnalysisObjective.PRODUCT_IMPROVEMENT.value: "产品改进分析",
    AnalysisObjective.GO_TO_MARKET.value: "市场进入分析",
    AnalysisObjective.INVESTMENT_DUE_DILIGENCE.value: "投资尽调分析",
    AnalysisObjective.COMPETITIVE_DEFENSE.value: "竞争防御分析",
    AnalysisObjective.POSITIONING_SWITCH.value: "定位转型分析",
    AnalysisObjective.PARTNERSHIP_EVALUATION.value: "合作评估分析",
    AnalysisObjective.FEATURE_BENCHMARK.value: "功能对标分析",
    "intelligence_collection": "信息收集",
    "market_analysis": "市场分析",
}

OBJECTIVE_LABELS_EN: dict[str, str] = {
    AnalysisObjective.PRODUCT_IMPROVEMENT.value: "Product improvement",
    AnalysisObjective.GO_TO_MARKET.value: "Go-to-market analysis",
    AnalysisObjective.INVESTMENT_DUE_DILIGENCE.value: "Investment due diligence",
    AnalysisObjective.COMPETITIVE_DEFENSE.value: "Competitive defense",
    AnalysisObjective.POSITIONING_SWITCH.value: "Positioning switch",
    AnalysisObjective.PARTNERSHIP_EVALUATION.value: "Partnership evaluation",
    AnalysisObjective.FEATURE_BENCHMARK.value: "Feature benchmark",
    "intelligence_collection": "Intelligence collection",
    "market_analysis": "Market analysis",
}

KNOWN_OBJECTIVE_CODES = frozenset(OBJECTIVE_LABELS_ZH.keys())


def looks_cjk(text: str | None) -> bool:
    return bool(text and _CJK_RE.search(text))


def _strip(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def prefer_language(*texts: str | None) -> str:
    """Return 'zh' if any hint contains CJK, else 'en'."""
    for t in texts:
        if looks_cjk(t):
            return "zh"
    return "en"


def label_for_objective_code(code: str, lang: str) -> str | None:
    table = OBJECTIVE_LABELS_ZH if lang == "zh" else OBJECTIVE_LABELS_EN
    return table.get(code)


def is_objective_code(value: str | None) -> bool:
    text = _strip(value)
    return bool(text) and text in KNOWN_OBJECTIVE_CODES


def resolve_collection_topic(
    *,
    scene: str | None = None,
    raw_message: str | None = None,
    objective: str | None = None,
    objective_code: str | None = None,
    language_hints: tuple[str | None, ...] = (),
) -> dict[str, str]:
    """Pick user-facing topic + provenance.

    Priority:
      1. scene
      2. raw_message
      3. readable label for AnalysisObjective enum
      4. non-enum objective text, else safe fallback
    """
    scene_s = _strip(scene)
    raw_s = _strip(raw_message)
    obj_s = _strip(objective)
    code_s = _strip(objective_code)

    if not code_s and is_objective_code(obj_s):
        code_s = obj_s

    if scene_s:
        return {
            "topic": scene_s,
            "topic_source": "scene",
            "objective_code": code_s or (obj_s if is_objective_code(obj_s) else ""),
        }

    if raw_s:
        return {
            "topic": raw_s,
            "topic_source": "raw_message",
            "objective_code": code_s or (obj_s if is_objective_code(obj_s) else ""),
        }

    lang = prefer_language(*(language_hints or ()), scene_s, raw_s, obj_s)
    if code_s and is_objective_code(code_s):
        label = label_for_objective_code(code_s, lang) or code_s
        return {
            "topic": label,
            "topic_source": "objective_label",
            "objective_code": code_s,
        }

    if obj_s and is_objective_code(obj_s):
        label = label_for_objective_code(obj_s, lang) or obj_s
        return {
            "topic": label,
            "topic_source": "objective_label",
            "objective_code": obj_s,
        }

    if obj_s and not is_objective_code(obj_s):
        # Free-text objective (already user-readable)
        return {
            "topic": obj_s,
            "topic_source": "objective",
            "objective_code": code_s,
        }

    fallback = "信息收集" if lang == "zh" else "Intelligence collection"
    return {
        "topic": fallback,
        "topic_source": "fallback",
        "objective_code": code_s,
    }


def apply_topic_to_markdown(markdown: str | None, topic: str) -> str | None:
    """Rewrite the 收集主题 line for legacy digests (no persistence change)."""
    if not markdown or not topic:
        return markdown
    import re

    updated, n = re.subn(
        r"(>\s*\*\*收集主题\*\*：)[^\n]*",
        rf"\g<1>{topic}",
        markdown,
        count=1,
    )
    return updated if n else markdown


def resolve_collection_topic_from_state(state: dict[str, Any] | None) -> dict[str, str]:
    """Resolve topic from workflow / task state (read path + formatter)."""
    state = state or {}
    validated = state.get("validated_input") or {}
    user_input = state.get("user_input") or {}
    optional = user_input.get("optional") or {}
    if not isinstance(optional, dict):
        optional = {}

    doc = state.get("collection_document") or {}
    if isinstance(doc, dict) and _strip(doc.get("topic")):
        return {
            "topic": _strip(doc.get("topic")),
            "topic_source": _strip(doc.get("topic_source")) or "collection_document",
            "objective_code": _strip(doc.get("objective_code"))
            or _strip(validated.get("objective_code"))
            or "",
        }

    scene = (
        validated.get("scene")
        or user_input.get("scene")
        or ""
    )
    raw_message = optional.get("raw_message") or ""
    objective_code = (
        validated.get("objective_code")
        or (user_input.get("objective") if is_objective_code(user_input.get("objective")) else "")
        or ""
    )
    # Prefer original enum for code; display objective may already be scene text
    objective = user_input.get("objective") or validated.get("objective") or ""

    # Company/product as weak language hints
    hints = (
        scene,
        raw_message,
        user_input.get("our_company"),
        user_input.get("product"),
        validated.get("our_company"),
        validated.get("product"),
    )
    return resolve_collection_topic(
        scene=scene,
        raw_message=raw_message,
        objective=objective,
        objective_code=objective_code,
        language_hints=hints,
    )
