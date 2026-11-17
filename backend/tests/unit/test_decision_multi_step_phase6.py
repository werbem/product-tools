"""Phase 6: multi-step PlanStep chains + ThinRouter metadata."""

from __future__ import annotations

import pytest

from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import DecisionEntities, EntitySlot
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import RoutingDecision
from app.application.services.decision_intent_extractor import DecisionIntentExtractor
from app.application.services.decision_multi_step import detect_multi_step_combo
from app.application.services.decision_planner import (
    DecisionPlanner,
    assert_no_implicit_deep,
)
from app.application.services.decision_routing import apply_decision_routing
from app.application.services.decision_thin_router import ThinRouter


@pytest.fixture(autouse=True)
def _default_routing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_PLANNER_ROUTING", "off")
    monkeypatch.setattr(
        "app.config.settings.settings.decision_planner_routing",
        "off",
        raising=False,
    )


def _ents(
    company: str | None,
    product: str | None,
    competitors: list[str] | None = None,
) -> DecisionEntities:
    comps = list(competitors or [])
    return DecisionEntities(
        company=EntitySlot(
            value=company,
            source="message" if company else "unknown",
            confidence=0.9 if company else 0.0,
        ),
        product=EntitySlot(
            value=product,
            source="message" if product else "unknown",
            confidence=0.9 if product else 0.0,
        ),
        competitors=EntitySlot(
            value=comps,
            source="message" if comps else "unknown",
            confidence=0.9 if comps else 0.0,
        ),
    )


class TestMultiStepDetect:
    def test_listing_only_not_combo(self) -> None:
        assert detect_multi_step_combo("抖音都有哪些竞品？") is None

    def test_listing_plus_analyze(self) -> None:
        assert (
            detect_multi_step_combo(
                "抖音都有哪些竞品？帮我完成抖音的竞品分析报告",
            )
            == "listing_then_analyze"
        )

    def test_collect_advise_and_analyze(self) -> None:
        assert (
            detect_multi_step_combo("帮我收集字节跳动抖音近期信息并给出运营建议")
            == "collect_then_advise"
        )
        assert (
            detect_multi_step_combo("帮我收集滴滴出行资料并做竞品分析")
            == "collect_then_analyze"
        )

    def test_nested_materials_not_combo(self) -> None:
        assert detect_multi_step_combo("帮我收集竞品分析报告相关资料") is None


class TestMultiStepPlanner:
    def test_listing_only_stays_short_answer(self) -> None:
        msg = "抖音都有哪些竞品？"
        intent = DecisionIntentExtractor().extract(msg, has_prior=False)
        plan = DecisionPlanner().plan(
            intent,
            _ents("抖音", "短视频", ["快手"]),
            DecisionContext(),
        )
        assert plan.execution_mode == "short_answer"
        assert plan.workflow_type == "simple_question"
        assert_no_implicit_deep(plan, intent)

    def test_listing_then_analyze_chain(self) -> None:
        msg = "抖音都有哪些竞品？帮我完成抖音的竞品分析报告"
        intent = DecisionIntentExtractor().extract(msg, has_prior=False)
        plan = DecisionPlanner().plan(
            intent,
            _ents("抖音", "短视频", []),
            DecisionContext(),
        )
        assert plan.execution_mode == "multi_step"
        assert [s.op for s in plan.steps] == ["list_competitors", "deep_analysis"]
        assert plan.workflow_type == "competitive_analysis"
        assert_no_implicit_deep(plan, intent)

    def test_collect_then_advise_chain(self) -> None:
        msg = "帮我收集字节跳动抖音近期信息并给出运营建议"
        intent = DecisionIntentExtractor().extract(msg, has_prior=False)
        plan = DecisionPlanner().plan(
            intent,
            _ents("字节跳动", "抖音"),
            DecisionContext(),
        )
        assert plan.execution_mode == "multi_step"
        assert [s.op for s in plan.steps] == [
            "intelligence_collection",
            "follow_up_short_answer",
        ]
        assert plan.workflow_type == "research"
        assert_no_implicit_deep(plan, intent)


class TestMultiStepThinRouter:
    def test_dispatch_attaches_steps_and_terminal_workflow(self) -> None:
        msg = "抖音都有哪些竞品？帮我完成抖音的竞品分析报告"
        intent = DecisionIntentExtractor().extract(msg, has_prior=False)
        plan = DecisionPlanner().plan(
            intent,
            _ents("抖音", "短视频", ["快手"]),
            DecisionContext(),
        )
        cap = ThinRouter().dispatch(plan)
        assert cap.capability == "multi_step"
        assert cap.routing.workflow_type == "competitive_analysis"
        assert cap.metadata.get("multi_step") is True
        assert cap.metadata.get("step_ops") == ["list_competitors", "deep_analysis"]
        assert cap.metadata.get("terminal_op") == "deep_analysis"
        assert cap.analysis_mode in ("fast", "full")

    def test_mode_on_listing_combo_routes_competitive_analysis(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DECISION_PLANNER_ROUTING", "on")
        msg = "抖音都有哪些竞品？帮我完成抖音的竞品分析报告"
        legacy = RoutingDecision(
            workflow_type="competitive_analysis",
            reason="legacy",
            confidence=0.9,
            legacy_workflow_kind="deep_analysis",
        )
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company="抖音",
            competitors=["快手"],
            product="短视频",
            confidence=0.9,
            raw_message=msg,
        )
        routing, meta, clarify = apply_decision_routing(
            message=msg,
            legacy_intent=intent,
            legacy_routing=legacy,
            has_prior=False,
            mode="on",
        )
        assert clarify is None
        assert routing.workflow_type == "competitive_analysis"
        assert meta is not None
        assert meta["capability"] == "multi_step"
        assert meta["execution_mode"] == "multi_step"
        assert meta["step_ops"] == ["list_competitors", "deep_analysis"]
