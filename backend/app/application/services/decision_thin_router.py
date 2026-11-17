"""Thin Router — ExecutionPlan → Capability / RoutingDecision (Phase 5).

No semantic regex. Maps Planner output onto legacy executor workflow labels.
Production cutover is gated by ``DECISION_PLANNER_ROUTING`` (off|shadow|on).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.application.dto.decision.adapters import execution_plan_to_routing_decision
from app.application.dto.decision.plan_contract import ExecutionPlan
from app.application.dto.routing_dto import RoutingDecision

CapabilityId = Literal[
    "reject_oos",
    "clarify",
    "short_answer",
    "follow_up",
    "research",
    "deep_analysis",
    "multi_step",
]

_MODE_TO_CAPABILITY: dict[str, CapabilityId] = {
    "oos": "reject_oos",
    "clarify": "clarify",
    "short_answer": "short_answer",
    "follow_up": "follow_up",
    "research": "research",
    "deep_fast": "deep_analysis",
    "deep_full": "deep_analysis",
    "multi_step": "multi_step",
}


class CapabilityDecision(BaseModel):
    """Thin-router output consumed by ConversationService executors."""

    capability: CapabilityId
    routing: RoutingDecision
    plan: ExecutionPlan
    analysis_mode: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ThinRouter:
    """Map ExecutionPlan → CapabilityDecision. No Intent inference."""

    def dispatch(self, plan: ExecutionPlan) -> CapabilityDecision:
        capability = _MODE_TO_CAPABILITY.get(plan.execution_mode, "short_answer")
        routing = execution_plan_to_routing_decision(plan)
        # Preserve plan.workflow_type when adapter would coarsen short_answer
        if plan.workflow_type in {
            "competitive_analysis",
            "research",
            "information_query",
            "simple_question",
            "follow_up",
            "out_of_scope",
        }:
            routing = routing.model_copy(
                update={
                    "workflow_type": plan.workflow_type,
                    "reason": plan.reason or routing.reason,
                    "confidence": float(plan.planner_confidence or routing.confidence),
                },
            )

        analysis_mode = None
        for step in plan.steps:
            if step.op in ("deep_analysis", "upgrade_analysis"):
                analysis_mode = str((step.args or {}).get("analysis_mode") or "") or None
                break
        if analysis_mode is None and plan.execution_mode == "deep_full":
            analysis_mode = "full"
        elif analysis_mode is None and plan.execution_mode == "deep_fast":
            analysis_mode = "fast"

        step_ops = [s.op for s in plan.steps]
        terminal_op = step_ops[-1] if step_ops else None
        meta: dict[str, Any] = {
            "execution_mode": plan.execution_mode,
            "plan_reason": plan.reason,
            "clarification_required": plan.clarification_required,
            "step_ops": step_ops,
            "terminal_op": terminal_op,
        }
        # Phase 6: multi_step capability; terminal workflow drives existing executors
        if plan.execution_mode == "multi_step":
            meta["multi_step"] = True
            meta["steps"] = [s.model_dump() for s in plan.steps]

        return CapabilityDecision(
            capability=capability,
            routing=routing,
            plan=plan,
            analysis_mode=analysis_mode,
            metadata=meta,
        )
