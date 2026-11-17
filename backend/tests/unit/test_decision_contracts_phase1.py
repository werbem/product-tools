"""Phase 1 decision contract + adapter unit tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.application.dto.decision import (
    DecisionContext,
    DecisionEntities,
    DecisionIntent,
    EntitySlot,
    ExecutionPlan,
    PlanStep,
    execution_plan_to_routing_decision,
    legacy_intent_to_decision_entities,
    routing_context_to_decision_context,
    workflow_type_to_execution_mode_hint,
)
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext


class TestDecisionIntentContract:
    def test_construct_analyze(self) -> None:
        intent = DecisionIntent(
            task_family="analyze",
            discourse="new",
            raw_message="帮我做竞品分析报告",
            confidence=0.9,
        )
        assert intent.task_family == "analyze"
        assert intent.ask_subtype is None

    def test_rejects_empty_message(self) -> None:
        with pytest.raises(ValidationError):
            DecisionIntent(task_family="ask", raw_message="  ")


class TestDecisionEntitiesContract:
    def test_helpers_and_missing(self) -> None:
        ents = DecisionEntities(
            company=EntitySlot(value="滴滴出行", source="message", confidence=0.9),
            product=EntitySlot(value="滴滴打车", source="memory", confidence=0.7),
            competitors=EntitySlot(
                value=["高德打车", "曹操出行"],
                source="curated",
                confidence=0.8,
            ),
            missing_slots=[],
        )
        assert ents.company_name() == "滴滴出行"
        assert ents.product_name() == "滴滴打车"
        assert ents.competitor_names() == ["高德打车", "曹操出行"]

    def test_invalid_missing_slot(self) -> None:
        with pytest.raises(ValidationError):
            DecisionEntities(missing_slots=["objective"])


class TestDecisionContextContract:
    def test_defaults(self) -> None:
        ctx = DecisionContext(has_prior_artifact=True, memory_company="滴滴出行")
        assert ctx.has_prior_artifact is True
        assert ctx.memory_competitors == []


class TestExecutionPlanContract:
    def test_follow_up_plan(self) -> None:
        plan = ExecutionPlan(
            execution_mode="follow_up",
            workflow_type="follow_up",
            steps=[PlanStep(op="short_answer", args={"use_prior": True})],
            planner_confidence=0.8,
            reason="advice_with_prior",
        )
        assert plan.clarification_required is False
        assert len(plan.steps) == 1


class TestAdapters:
    def test_legacy_intent_to_entities(self) -> None:
        legacy = IntentUnderstandingResult(
            type="competitive_analysis",
            company="滴滴出行",
            competitors=["高德打车"],
            product="滴滴打车",
            confidence=0.88,
            missing_fields=[],
            raw_message="调研滴滴",
        )
        ents = legacy_intent_to_decision_entities(legacy)
        assert ents.company_name() == "滴滴出行"
        assert ents.competitor_names() == ["高德打车"]
        assert ents.company.source == "unknown"

    def test_routing_context_to_decision_context(self) -> None:
        ctx = ConversationRoutingContext(
            conversation_id="c1",
            project_id="p1",
            has_prior_analysis=True,
        )
        out = routing_context_to_decision_context(
            ctx,
            memory_company="滴滴出行",
            memory_competitors=["曹操出行"],
            memory_product="滴滴打车",
        )
        assert out.has_prior_artifact is True
        assert out.conversation_id == "c1"
        assert out.memory_company == "滴滴出行"
        assert out.memory_competitors == ["曹操出行"]

    def test_plan_follow_up_to_routing_decision(self) -> None:
        plan = ExecutionPlan(
            execution_mode="follow_up",
            workflow_type="follow_up",
            planner_confidence=0.8,
            reason="follow_up_advice_with_prior_context",
        )
        rd = execution_plan_to_routing_decision(plan)
        assert rd.workflow_type == "follow_up"
        assert rd.legacy_workflow_kind is None
        assert "follow_up" in rd.reason

    def test_plan_deep_to_routing_decision(self) -> None:
        plan = ExecutionPlan(
            execution_mode="deep_fast",
            workflow_type="competitive_analysis",
            planner_confidence=0.9,
            reason="explicit_ca",
        )
        rd = execution_plan_to_routing_decision(plan)
        assert rd.workflow_type == "competitive_analysis"
        assert rd.legacy_workflow_kind == "deep_analysis"

    def test_plan_research_to_routing_decision(self) -> None:
        plan = ExecutionPlan(
            execution_mode="research",
            workflow_type="research",
            planner_confidence=0.85,
            reason="collection",
        )
        rd = execution_plan_to_routing_decision(plan)
        assert rd.workflow_type == "research"
        assert rd.legacy_workflow_kind == "intelligence_collection"

    def test_workflow_hint_table(self) -> None:
        assert workflow_type_to_execution_mode_hint("follow_up") == "follow_up"
        assert workflow_type_to_execution_mode_hint("competitive_analysis") == "deep_fast"
        assert workflow_type_to_execution_mode_hint("out_of_scope") == "oos"
