"""Analysis-deliverable Intent semantics (A/B + C1–C4)."""

from __future__ import annotations

import pytest

from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import DecisionEntities, EntitySlot
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.analysis_deliverable_semantics import (
    looks_like_analysis_deliverable,
    looks_like_collection_digest,
)
from app.application.services.decision_intent_extractor import DecisionIntentExtractor
from app.application.services.decision_planner import DecisionPlanner, assert_no_implicit_deep
from app.application.services.intent_mapper import resolve_workflow_kind


@pytest.mark.parametrize(
    "message,expect_family,expect_kind",
    [
        (
            "帮我完成深度的竞品调研报告，我需要针对滴滴及滴滴的竞品公司",
            "analyze",
            "deep_analysis",
        ),
        ("出一份竞品调研报告", "analyze", "deep_analysis"),
        ("调研报告：滴滴 vs 高德", "analyze", "deep_analysis"),
        ("做一份滴滴的竞品研究报告", "analyze", "deep_analysis"),
        ("深度竞品研究，输出报告", "analyze", "deep_analysis"),
        ("帮我写竞品尽调报告", "analyze", "deep_analysis"),
        ("帮我对标一下滴滴和曹操", "analyze", "deep_analysis"),
        ("帮我做竞品对标分析", "analyze", "deep_analysis"),
        ("competitor research report for Didi", "analyze", "deep_analysis"),
        ("competitive intelligence report on Didi", "analyze", "deep_analysis"),
        ("请做竞品 benchmarking report", "analyze", "deep_analysis"),
        ("帮我做市场调研报告（滴滴）", "analyze", "deep_analysis"),
        ("行业研究报告：网约车", "analyze", "deep_analysis"),
        ("出一份竞品情报报告", "analyze", "deep_analysis"),
        ("帮我调研竞品并出报告", "analyze", "deep_analysis"),
        ("出一份竞品情报摘要", "collect", "intelligence_collection"),
        ("帮我调研一下美团酒店近期动态", "collect", "intelligence_collection"),
        ("帮我收集竞品分析报告相关资料", "collect", "intelligence_collection"),
        ("调研滴滴打车华南市场的发展趋势", "collect", "intelligence_collection"),
    ],
)
def test_deliverable_semantics_family_and_kind(
    message: str,
    expect_family: str,
    expect_kind: str,
) -> None:
    if "情报摘要" in message:
        assert looks_like_collection_digest(message)
        assert not looks_like_analysis_deliverable(message)
    if expect_family == "analyze":
        assert looks_like_analysis_deliverable(message) or "分析报告" in message

    fam = DecisionIntentExtractor().extract(message, has_prior=False).task_family
    assert fam == expect_family

    legacy = IntentUnderstandingResult(
        type="competitive_analysis",
        company="滴滴",
        competitors=["曹操出行"],
        product="打车",
        confidence=0.9,
        raw_message=message,
    )
    assert resolve_workflow_kind(legacy, message) == expect_kind


def test_planner_diaoyan_baogao_launches_analyze_not_research() -> None:
    msg = "帮我完成深度的竞品调研报告，我需要针对滴滴及滴滴的竞品公司"
    intent = DecisionIntentExtractor().extract(msg, has_prior=True)
    ents = DecisionEntities(
        company=EntitySlot(value="滴滴", source="message", confidence=0.9),
        product=EntitySlot(value="打车", source="message", confidence=0.9),
        competitors=EntitySlot(value=["曹操出行"], source="message", confidence=0.9),
    )
    plan = DecisionPlanner().plan(intent, ents, DecisionContext(has_prior_artifact=True))
    assert intent.task_family == "analyze"
    assert plan.execution_mode in ("deep_fast", "deep_full")
    assert plan.workflow_type == "competitive_analysis"
    assert_no_implicit_deep(plan, intent)
