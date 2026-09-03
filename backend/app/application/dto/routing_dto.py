"""Routing decision DTOs (Phase 2 Task Router)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

WorkflowType = Literal[
    "competitive_analysis",
    "research",
    "information_query",
    "simple_question",
    "follow_up",
    "out_of_scope",
]

LegacyWorkflowKind = Literal["deep_analysis", "intelligence_collection"]


class RoutingDecision(BaseModel):
    workflow_type: WorkflowType
    confidence: float = 1.0
    reason: str = ""
    legacy_workflow_kind: LegacyWorkflowKind | None = None

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "workflow_type": self.workflow_type,
            "confidence": self.confidence,
            "reason": self.reason,
            "legacy_workflow_kind": self.legacy_workflow_kind,
        }


class ConversationRoutingContext(BaseModel):
    """Optional conversation/project hints for future follow_up routing."""

    conversation_id: str | None = None
    project_id: str | None = None
    has_prior_analysis: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
