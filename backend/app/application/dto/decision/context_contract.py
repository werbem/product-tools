"""Decision Context / Memory snapshot contract (Phase 1).

Provides prior workflow and memory hints. Must not silently override
an explicit user Intent expressed in the current message.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

PriorWorkflowType = Literal[
    "competitive_analysis",
    "research",
    "information_query",
    "simple_question",
    "follow_up",
    "out_of_scope",
    "deep_analysis",
    "intelligence_collection",
]


class DecisionContext(BaseModel):
    """Flat conversation + memory snapshot for Planner input."""

    conversation_id: str | None = None
    project_id: str | None = None
    has_prior_artifact: bool = False
    prior_workflow_type: PriorWorkflowType | None = None
    prior_task_id: str | None = None
    prior_report_id: str | None = None
    memory_company: str | None = None
    memory_competitors: list[str] = Field(default_factory=list)
    memory_product: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
