"""Decision Intent contract (Phase 1).

Intent answers: what task does the user want this turn?
It does NOT select workflow launch or execution steps.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

TaskFamily = Literal["analyze", "collect", "ask", "advise_prior", "oos"]
AskSubtype = Literal["listing", "definition", "dynamics", "advice", "other"]
Discourse = Literal["new", "continue_prior", "upgrade_prior"]


class DecisionIntent(BaseModel):
    """Target Intent schema for the decision architecture."""

    task_family: TaskFamily
    discourse: Discourse = "new"
    ask_subtype: AskSubtype | None = None
    objective: str | None = None
    focus: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    raw_message: str
    signals: list[str] = Field(default_factory=list)

    @field_validator("raw_message")
    @classmethod
    def _nonempty_message(cls, value: str) -> str:
        stripped = (value or "").strip()
        if not stripped:
            raise ValueError("raw_message must not be empty")
        return stripped

    @field_validator("objective", "focus", mode="before")
    @classmethod
    def _strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None
