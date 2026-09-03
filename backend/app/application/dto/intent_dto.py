"""Intent understanding DTOs."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

IntentType = Literal["competitive_analysis", "unsupported"]
MISSING_FIELD_NAMES = frozenset({"company", "competitors", "product", "objective"})

KNOWN_OBJECTIVES = frozenset({
    "product_improvement",
    "go_to_market",
    "investment_due_diligence",
    "competitive_defense",
    "positioning_switch",
    "partnership_evaluation",
    "feature_benchmark",
})


def _strip_or_none(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_competitors(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in values:
        cleaned = item.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


class IntentLLMOutput(BaseModel):
    type: IntentType
    company: str | None = None
    competitors: list[str] = Field(default_factory=list)
    product: str | None = None
    objective: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    @field_validator("company", "product", "objective", mode="before")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        return _strip_or_none(value) if isinstance(value, str) else value

    @field_validator("competitors", mode="before")
    @classmethod
    def normalize_competitors(cls, value: list[str] | None) -> list[str]:
        return _normalize_competitors(value or [])


class IntentUnderstandingResult(BaseModel):
    type: IntentType
    company: str | None = None
    competitors: list[str] = Field(default_factory=list)
    product: str | None = None
    objective: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    raw_message: str

    @field_validator("company", "product", "objective", "clarification_question", mode="before")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        return _strip_or_none(value) if isinstance(value, str) else value

    @field_validator("competitors", mode="before")
    @classmethod
    def normalize_competitors(cls, value: list[str] | None) -> list[str]:
        return _normalize_competitors(value or [])

    @field_validator("missing_fields")
    @classmethod
    def validate_missing_fields(cls, value: list[str]) -> list[str]:
        invalid = [f for f in value if f not in MISSING_FIELD_NAMES]
        if invalid:
            raise ValueError(f"invalid missing_fields: {invalid}")
        return value

    @field_validator("raw_message")
    @classmethod
    def validate_raw_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("raw_message must not be empty")
        return stripped


class IntentUnderstandingRequest(BaseModel):
    message: str
    partial: IntentUnderstandingResult | None = None
    conversation_id: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message must not be empty")
        return stripped
