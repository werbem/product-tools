"""Decision Plan contract (Phase 1).

Planner (Phase 4) emits ExecutionPlan. Thin Router (Phase 5) maps plan → executor.
Implicit deep_* without analyze/upgrade signal is forbidden in the target Planner.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ExecutionMode = Literal[
    "clarify",
    "short_answer",
    "research",
    "deep_fast",
    "deep_full",
    "follow_up",
    "multi_step",
    "oos",
]

# Legacy-compatible workflow labels for Thin Router mapping
PlanWorkflowType = Literal[
    "competitive_analysis",
    "research",
    "information_query",
    "simple_question",
    "follow_up",
    "out_of_scope",
]


class PlanStep(BaseModel):
    """One step in a (possibly multi-step) execution plan."""

    op: str
    args: dict[str, Any] = Field(default_factory=dict)
    optional: bool = False


class ExecutionPlan(BaseModel):
    """Planner output: how to execute this turn.

    Contract note: do not emit deep_fast/deep_full unless Intent.task_family
    is analyze or discourse is upgrade_prior (enforced in Planner Phase 4).
    """

    clarification_required: bool = False
    clarification_question: str | None = None
    execution_mode: ExecutionMode
    workflow_type: PlanWorkflowType
    steps: list[PlanStep] = Field(default_factory=list)
    planner_confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reason: str = ""
