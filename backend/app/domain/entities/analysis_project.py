"""AnalysisProject entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.domain.entities.copilot_common import utc_now


@dataclass
class AnalysisProject:
    id: str
    title: str
    objective: str | None = None
    status: Literal["active", "archived"] = "active"
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title must not be empty")
