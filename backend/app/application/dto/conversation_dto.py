"""Conversation turn result DTO."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import RoutingDecision
from app.domain.entities.conversation import Conversation
from app.domain.entities.message import Message

TurnStatus = Literal[
    "needs_clarification",
    "unsupported",
    "analysis_started",
    "out_of_scope",
    "unsupported_workflow",
    "query_answered",
    "follow_up_answered",
    "question_answered",
    "workflow_busy",
]


class ConversationTurnResult(BaseModel):
    conversation: Conversation
    user_message: Message
    assistant_message: Message
    intent: IntentUnderstandingResult
    status: TurnStatus
    task_id: str | None = None
    report_id: str | None = None
    routing_decision: RoutingDecision | None = None

    model_config = {"arbitrary_types_allowed": True}
