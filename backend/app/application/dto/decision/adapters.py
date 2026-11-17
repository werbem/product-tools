"""Legacy ↔ Decision Architecture adapters (Phase 1).

Lossy but explicit. Not wired into ConversationService until Phase 5.
"""

from __future__ import annotations

from typing import Any

from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import (
    DecisionEntities,
    EntitySlot,
    EntitySource,
)
from app.application.dto.decision.plan_contract import ExecutionMode, ExecutionPlan
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import (
    ConversationRoutingContext,
    RoutingDecision,
    WorkflowType,
)

_MODE_TO_WORKFLOW: dict[ExecutionMode, WorkflowType] = {
    "clarify": "simple_question",  # clarify is handled pre-route today
    "short_answer": "simple_question",
    "research": "research",
    "deep_fast": "competitive_analysis",
    "deep_full": "competitive_analysis",
    "follow_up": "follow_up",
    "multi_step": "competitive_analysis",
    "oos": "out_of_scope",
}

# Prefer plan.workflow_type when present; fallback via execution_mode
_WORKFLOW_ALIASES: dict[str, WorkflowType] = {
    "competitive_analysis": "competitive_analysis",
    "research": "research",
    "information_query": "information_query",
    "simple_question": "simple_question",
    "follow_up": "follow_up",
    "out_of_scope": "out_of_scope",
}


def legacy_intent_to_decision_entities(
    intent: IntentUnderstandingResult,
    *,
    default_source: EntitySource = "unknown",
) -> DecisionEntities:
    """Map legacy IntentUnderstandingResult slots → DecisionEntities.

    Sources default to ``unknown`` until Phase 3 tracks provenance.
    """
    src: EntitySource = default_source
    company = EntitySlot(
        value=intent.company,
        source=src,
        confidence=float(intent.confidence or 0.0) if intent.company else 0.0,
    )
    product = EntitySlot(
        value=intent.product,
        source=src,
        confidence=float(intent.confidence or 0.0) if intent.product else 0.0,
    )
    comps = list(intent.competitors or [])
    competitors = EntitySlot(
        value=comps,
        source=src,
        confidence=float(intent.confidence or 0.0) if comps else 0.0,
    )
    missing: list[str] = []
    for field in intent.missing_fields or []:
        if field in {"company", "product", "competitors"}:
            missing.append(field)
    return DecisionEntities(
        company=company,
        product=product,
        competitors=competitors,
        missing_slots=missing,
    )


def routing_context_to_decision_context(
    ctx: ConversationRoutingContext | None,
    *,
    prior_workflow_type: str | None = None,
    prior_task_id: str | None = None,
    prior_report_id: str | None = None,
    memory_company: str | None = None,
    memory_competitors: list[str] | None = None,
    memory_product: str | None = None,
) -> DecisionContext:
    """Map ConversationRoutingContext (+ optional memory flat fields) → DecisionContext."""
    meta: dict[str, Any] = {}
    if ctx is not None:
        meta = dict(ctx.metadata or {})
    return DecisionContext(
        conversation_id=ctx.conversation_id if ctx else None,
        project_id=ctx.project_id if ctx else None,
        has_prior_artifact=bool(ctx and ctx.has_prior_analysis),
        prior_workflow_type=prior_workflow_type,  # type: ignore[arg-type]
        prior_task_id=prior_task_id,
        prior_report_id=prior_report_id,
        memory_company=memory_company,
        memory_competitors=list(memory_competitors or []),
        memory_product=memory_product,
        metadata=meta,
    )


def execution_plan_to_routing_decision(plan: ExecutionPlan) -> RoutingDecision:
    """Map ExecutionPlan → legacy RoutingDecision (Thin Router stub).

    Unused in production until Phase 5. Prefer ``plan.workflow_type`` when valid.
    """
    wf = _WORKFLOW_ALIASES.get(plan.workflow_type) or _MODE_TO_WORKFLOW.get(
        plan.execution_mode,
        "out_of_scope",
    )
    legacy_kind = None
    if plan.execution_mode in ("deep_fast", "deep_full"):
        legacy_kind = "deep_analysis"
    elif plan.execution_mode == "research":
        legacy_kind = "intelligence_collection"
    return RoutingDecision(
        workflow_type=wf,
        confidence=float(plan.planner_confidence or 0.5),
        reason=plan.reason or f"plan_mode_{plan.execution_mode}",
        legacy_workflow_kind=legacy_kind,  # type: ignore[arg-type]
    )


def workflow_type_to_execution_mode_hint(workflow_type: str) -> ExecutionMode:
    """Best-effort reverse hint for docs/tests (not a Planner)."""
    mapping: dict[str, ExecutionMode] = {
        "competitive_analysis": "deep_fast",
        "research": "research",
        "information_query": "short_answer",
        "simple_question": "short_answer",
        "follow_up": "follow_up",
        "out_of_scope": "oos",
    }
    return mapping.get(workflow_type, "short_answer")
