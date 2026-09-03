"""Message entity (append-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.domain.entities.copilot_common import utc_now


@dataclass
class Message:
    id: str
    conversation_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: datetime = field(default_factory=utc_now)
    task_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.content = self.content.strip()
        if not self.content:
            raise ValueError("content must not be empty")
        if not self.conversation_id.strip():
            raise ValueError("conversation_id must not be empty")
