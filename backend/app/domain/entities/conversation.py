"""Conversation entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.domain.entities.copilot_common import utc_now


@dataclass
class Conversation:
    id: str
    project_id: str
    title: str | None = None
    status: Literal["active", "completed", "archived"] = "active"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.project_id.strip():
            raise ValueError("project_id must not be empty")
        if self.title is not None:
            self.title = self.title.strip() or None
