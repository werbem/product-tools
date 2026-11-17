"""Decision-stack routing helper (Phase 5) — Intent → Entity → Planner → ThinRouter.

Used by ConversationService behind ``DECISION_PLANNER_ROUTING``.
Default mode is ``off`` (legacy Router only).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Literal

from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import DecisionEntities
from app.application.dto.decision.intent_contract import DecisionIntent
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import RoutingDecision
from app.application.services.decision_entity_extractor import DecisionEntityExtractor
from app.application.services.decision_intent_extractor import (
    DecisionIntentExtractor,
    shadow_compare_intent_vs_router_workflow,
)
from app.application.services.decision_planner import (
    DecisionPlanner,
    assert_no_implicit_deep,
    shadow_compare_plan_vs_router_workflow,
)
from app.application.services.decision_thin_router import CapabilityDecision, ThinRouter

logger = logging.getLogger(__name__)

DecisionRoutingMode = Literal["off", "shadow", "on"]


def get_decision_planner_routing_mode() -> DecisionRoutingMode:
    """Read DECISION_PLANNER_ROUTING env / settings (off|shadow|on)."""
    raw = (os.getenv("DECISION_PLANNER_ROUTING") or "off").strip().lower()
    try:
        from app.config.settings import settings

        raw = (getattr(settings, "decision_planner_routing", None) or raw or "off")
        raw = str(raw).strip().lower()
    except Exception:
        pass
    if raw in ("shadow", "on", "off"):
        return raw  # type: ignore[return-value]
    return "off"


def build_decision_context(
    *,
    conversation_id: str | None,
    project_id: str | None,
    has_prior: bool,
    memory: Any | None,
) -> DecisionContext:
    mem_company = None
    mem_product = None
    mem_comps: list[str] = []
    if memory is not None:
        ents = getattr(memory, "entities", None)
        if ents is not None:
            mem_company = getattr(ents, "our_company", None)
            mem_product = getattr(ents, "product", None)
            mem_comps = list(getattr(ents, "competitors", None) or [])
    return DecisionContext(
        conversation_id=conversation_id,
        project_id=project_id,
        has_prior_artifact=has_prior,
        memory_company=mem_company,
        memory_product=mem_product,
        memory_competitors=mem_comps,
    )


def run_decision_stack(
    *,
    message: str,
    legacy_intent: IntentUnderstandingResult,
    has_prior: bool,
    memory: Any | None = None,
    conversation_id: str | None = None,
    project_id: str | None = None,
    analysis_mode_hint: str | None = None,
    intent_extractor: DecisionIntentExtractor | None = None,
    entity_extractor: DecisionEntityExtractor | None = None,
    planner: DecisionPlanner | None = None,
    thin_router: ThinRouter | None = None,
) -> tuple[DecisionIntent, DecisionEntities, CapabilityDecision]:
    """Execute Intent → Entity → Planner → ThinRouter (no side effects)."""
    intent_ex = intent_extractor or DecisionIntentExtractor()
    entity_ex = entity_extractor or DecisionEntityExtractor()
    plan_ex = planner or DecisionPlanner()
    thin = thin_router or ThinRouter()

    decision_intent = intent_ex.extract(message, has_prior=has_prior)
    ctx = build_decision_context(
        conversation_id=conversation_id,
        project_id=project_id,
        has_prior=has_prior,
        memory=memory,
    )
    entities = entity_ex.extract(
        message,
        legacy_intent=legacy_intent,
        context=ctx,
        memory=memory,
        prior_company=legacy_intent.company if has_prior else None,
        prior_product=legacy_intent.product if has_prior else None,
        prior_competitors=list(legacy_intent.competitors or []) if has_prior else None,
    )
    plan = plan_ex.plan(
        decision_intent,
        entities,
        ctx,
        analysis_mode_hint=analysis_mode_hint,
    )
    assert_no_implicit_deep(plan, decision_intent)
    capability = thin.dispatch(plan)
    return decision_intent, entities, capability


def apply_decision_routing(
    *,
    message: str,
    legacy_intent: IntentUnderstandingResult,
    legacy_routing: RoutingDecision,
    has_prior: bool,
    memory: Any | None = None,
    conversation_id: str | None = None,
    project_id: str | None = None,
    analysis_mode_hint: str | None = None,
    mode: DecisionRoutingMode | None = None,
) -> tuple[RoutingDecision, dict[str, Any] | None, str | None]:
    """Return (routing, decision_stack_meta, planner_clarify_question).

    - off: legacy routing unchanged
    - shadow: legacy routing + metadata comparison
    - on: thin-router routing (planner clarify question when required)
    """
    resolved_mode = mode or get_decision_planner_routing_mode()
    if resolved_mode == "off":
        return legacy_routing, None, None

    try:
        decision_intent, entities, capability = run_decision_stack(
            message=message,
            legacy_intent=legacy_intent,
            has_prior=has_prior,
            memory=memory,
            conversation_id=conversation_id,
            project_id=project_id,
            analysis_mode_hint=analysis_mode_hint,
        )
    except Exception:
        logger.exception("decision_stack_failed mode=%s", resolved_mode)
        return legacy_routing, {"error": "decision_stack_failed", "mode": resolved_mode}, None

    plan = capability.plan
    intent_shadow = shadow_compare_intent_vs_router_workflow(
        decision_intent=decision_intent,
        router_workflow_type=legacy_routing.workflow_type,
    )
    plan_shadow = shadow_compare_plan_vs_router_workflow(
        plan=plan,
        router_workflow_type=legacy_routing.workflow_type,
    )
    meta: dict[str, Any] = {
        "mode": resolved_mode,
        "capability": capability.capability,
        "execution_mode": plan.execution_mode,
        "plan_reason": plan.reason,
        "planner_confidence": plan.planner_confidence,
        "decision_intent": decision_intent.model_dump(),
        "entities": {
            "company": entities.company_name(),
            "product": entities.product_name(),
            "competitors": entities.competitor_names(),
            "company_source": entities.company.source,
            "missing_slots": list(entities.missing_slots),
        },
        "shadow_intent": intent_shadow,
        "shadow_plan": plan_shadow,
        "legacy_workflow_type": legacy_routing.workflow_type,
        "legacy_reason": legacy_routing.reason,
        "analysis_mode": capability.analysis_mode,
        "step_ops": list((capability.metadata or {}).get("step_ops") or []),
        "terminal_op": (capability.metadata or {}).get("terminal_op"),
        "multi_step": bool((capability.metadata or {}).get("multi_step")),
    }

    if resolved_mode == "shadow":
        return legacy_routing, meta, None

    # mode == on
    clarify_q = plan.clarification_question if plan.clarification_required else None
    return capability.routing, meta, clarify_q
