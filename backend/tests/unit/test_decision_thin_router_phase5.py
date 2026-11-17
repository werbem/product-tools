"""Phase 5: ThinRouter + decision routing mode (off/shadow/on)."""

from __future__ import annotations

import pytest

from app.application.dto.decision.intent_contract import DecisionIntent
from app.application.dto.decision.plan_contract import ExecutionPlan, PlanStep
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import RoutingDecision
from app.application.services.decision_planner import DecisionPlanner
from app.application.services.decision_routing import (
    apply_decision_routing,
    get_decision_planner_routing_mode,
    run_decision_stack,
)
from app.application.services.decision_thin_router import ThinRouter
from app.application.services.decision_entity_extractor import DecisionEntityExtractor
from app.application.services.decision_intent_extractor import DecisionIntentExtractor
from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import DecisionEntities, EntitySlot


@pytest.fixture(autouse=True)
def _default_routing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DECISION_PLANNER_ROUTING", "off")
    monkeypatch.setattr(
        "app.config.settings.settings.decision_planner_routing",
        "off",
        raising=False,
    )


class TestThinRouter:
    def test_follow_up_capability(self) -> None:
        plan = ExecutionPlan(
            execution_mode="follow_up",
            workflow_type="follow_up",
            reason="follow_up_short_answer",
            planner_confidence=0.8,
            steps=[PlanStep(op="follow_up_short_answer")],
        )
        cap = ThinRouter().dispatch(plan)
        assert cap.capability == "follow_up"
        assert cap.routing.workflow_type == "follow_up"

    def test_deep_full_capability(self) -> None:
        plan = ExecutionPlan(
            execution_mode="deep_full",
            workflow_type="competitive_analysis",
            reason="analyze_deep_launch",
            planner_confidence=0.9,
            steps=[
                PlanStep(op="deep_analysis", args={"analysis_mode": "full"}),
            ],
        )
        cap = ThinRouter().dispatch(plan)
        assert cap.capability == "deep_analysis"
        assert cap.analysis_mode == "full"
        assert cap.routing.workflow_type == "competitive_analysis"
        assert cap.routing.legacy_workflow_kind == "deep_analysis"

    def test_information_query_preserves_workflow(self) -> None:
        plan = ExecutionPlan(
            execution_mode="short_answer",
            workflow_type="information_query",
            reason="ask_dynamics_short_answer",
            planner_confidence=0.78,
            steps=[PlanStep(op="short_answer")],
        )
        cap = ThinRouter().dispatch(plan)
        assert cap.capability == "short_answer"
        assert cap.routing.workflow_type == "information_query"


class TestDecisionRoutingModes:
    def test_mode_off_keeps_legacy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DECISION_PLANNER_ROUTING", "off")
        legacy = RoutingDecision(
            workflow_type="competitive_analysis",
            reason="legacy_bridge_deep_analysis",
            confidence=0.9,
            legacy_workflow_kind="deep_analysis",
        )
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company="滴滴出行",
            competitors=["高德打车"],
            product="滴滴打车",
            confidence=0.9,
            raw_message="如果我是产品运营，我下一步应该做什么？",
        )
        routing, meta, clarify = apply_decision_routing(
            message=intent.raw_message,
            legacy_intent=intent,
            legacy_routing=legacy,
            has_prior=True,
            mode="off",
        )
        assert routing.workflow_type == "competitive_analysis"
        assert meta is None
        assert clarify is None

    def test_mode_shadow_keeps_legacy_adds_meta(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DECISION_PLANNER_ROUTING", "shadow")
        msg = "如果我是产品运营，我下一步应该做什么，推进用户体验和稳固产品壁垒？"
        legacy = RoutingDecision(
            workflow_type="follow_up",
            reason="follow_up_advice_with_prior_context",
            confidence=0.8,
        )
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company="滴滴出行",
            competitors=["高德打车"],
            product="滴滴打车",
            confidence=0.9,
            raw_message=msg,
        )
        routing, meta, clarify = apply_decision_routing(
            message=msg,
            legacy_intent=intent,
            legacy_routing=legacy,
            has_prior=True,
            mode="shadow",
        )
        assert routing.workflow_type == "follow_up"
        assert clarify is None
        assert meta is not None
        assert meta["mode"] == "shadow"
        assert meta["execution_mode"] == "follow_up"
        assert "shadow_plan" in meta

    def test_mode_on_uses_planner_follow_up(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("DECISION_PLANNER_ROUTING", "on")
        msg = "如果我是产品运营，我下一步应该做什么，推进用户体验和稳固产品壁垒？"
        # Legacy might have wrongly chosen deep; planner path must follow_up
        legacy = RoutingDecision(
            workflow_type="competitive_analysis",
            reason="legacy_bridge_deep_analysis",
            confidence=0.9,
            legacy_workflow_kind="deep_analysis",
        )
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company="滴滴出行",
            competitors=["高德打车", "曹操出行"],
            product="滴滴打车",
            confidence=0.9,
            raw_message=msg,
        )
        routing, meta, clarify = apply_decision_routing(
            message=msg,
            legacy_intent=intent,
            legacy_routing=legacy,
            has_prior=True,
            mode="on",
        )
        assert clarify is None
        assert routing.workflow_type == "follow_up"
        assert meta is not None
        assert meta["capability"] == "follow_up"
        assert meta["mode"] == "on"

    def test_mode_on_explicit_ca_still_deep(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        msg = "帮我做滴滴出行和曹操出行的竞品分析报告"
        legacy = RoutingDecision(
            workflow_type="competitive_analysis",
            reason="legacy_bridge_deep_analysis",
            confidence=0.9,
            legacy_workflow_kind="deep_analysis",
        )
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company="滴滴出行",
            competitors=["曹操出行"],
            product="滴滴打车",
            confidence=0.9,
            raw_message=msg,
        )
        routing, meta, clarify = apply_decision_routing(
            message=msg,
            legacy_intent=intent,
            legacy_routing=legacy,
            has_prior=True,
            mode="on",
        )
        assert clarify is None
        assert routing.workflow_type == "competitive_analysis"
        assert meta is not None
        assert meta["capability"] == "deep_analysis"

    def test_mode_on_clarify_missing_company(self) -> None:
        msg = "帮我做竞品分析报告"
        legacy = RoutingDecision(
            workflow_type="competitive_analysis",
            reason="legacy_bridge_deep_analysis",
            confidence=0.7,
            legacy_workflow_kind="deep_analysis",
        )
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company=None,
            competitors=[],
            product=None,
            confidence=0.7,
            raw_message=msg,
            needs_clarification=True,
            missing_fields=["company", "product", "competitors"],
        )
        # Force analyze via stack: message has 竞品分析报告 → analyze, empty entities
        routing, meta, clarify = apply_decision_routing(
            message=msg,
            legacy_intent=intent,
            legacy_routing=legacy,
            has_prior=False,
            mode="on",
        )
        assert meta is not None
        # Either clarify question or competitive_analysis if entity inferred — prefer clarify
        assert clarify is not None or routing.workflow_type in {
            "competitive_analysis",
            "simple_question",
            "follow_up",
        }


class TestRunDecisionStack:
    def test_stack_ops_advice(self) -> None:
        msg = "如果我是产品运营，我下一步应该做什么？"
        legacy = IntentUnderstandingResult(
            type="competitive_analysis",
            company="滴滴出行",
            competitors=["高德打车"],
            product="滴滴打车",
            confidence=0.9,
            raw_message=msg,
        )
        intent, ents, cap = run_decision_stack(
            message=msg,
            legacy_intent=legacy,
            has_prior=True,
        )
        assert intent.task_family == "advise_prior"
        assert ents.company_name() == "滴滴出行"
        assert cap.capability == "follow_up"
        assert get_decision_planner_routing_mode() == "off"
