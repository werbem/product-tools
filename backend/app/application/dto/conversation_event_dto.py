"""Conversation SSE event DTO."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ConversationEventType = Literal[
    "connected",
    "analysis_started",
    "phase_update",
    "artifact_created",
    "analysis_completed",
    "analysis_failed",
    "heartbeat",
]


class ConversationEvent(BaseModel):
    event: ConversationEventType
    conversation_id: str
    task_id: str | None = None
    timestamp: datetime
    data: dict[str, Any] = Field(default_factory=dict)
