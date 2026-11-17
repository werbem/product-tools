"""Decision Entity contract (Phase 1).

Entity fills slots from message / prior / memory / curated knowledge.
Filled slots do NOT imply Deep Analysis launch.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

EntitySource = Literal[
    "message",
    "prior",
    "memory",
    "curated",
    "inferred",
    "unknown",
]

ENTITY_SLOT_NAMES = frozenset({"company", "product", "competitors", "time_range"})


class EntitySlot(BaseModel):
    """One entity value with provenance."""

    value: str | list[str] | None = None
    source: EntitySource = "unknown"
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class DecisionEntities(BaseModel):
    """Target Entity schema for the decision architecture.

    Principle: slot completeness ≠ must start Deep Analysis.
    """

    company: EntitySlot = Field(default_factory=EntitySlot)
    product: EntitySlot = Field(default_factory=EntitySlot)
    competitors: EntitySlot = Field(
        default_factory=lambda: EntitySlot(value=[]),
    )
    time_range: EntitySlot = Field(default_factory=EntitySlot)
    missing_slots: list[str] = Field(default_factory=list)

    @field_validator("missing_slots")
    @classmethod
    def _validate_missing(cls, value: list[str]) -> list[str]:
        invalid = [f for f in value if f not in ENTITY_SLOT_NAMES]
        if invalid:
            raise ValueError(f"invalid missing_slots: {invalid}")
        return value

    def company_name(self) -> str | None:
        raw = self.company.value
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    def product_name(self) -> str | None:
        raw = self.product.value
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
        return None

    def competitor_names(self) -> list[str]:
        raw = self.competitors.value
        if isinstance(raw, list):
            return [str(x).strip() for x in raw if str(x).strip()]
        if isinstance(raw, str) and raw.strip():
            return [raw.strip()]
        return []
