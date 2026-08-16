"""Evaluation result data structures (standalone, not production DTOs)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class MetricResult:
    """A single metric's evaluation result."""
    score: float | None
    details: dict = field(default_factory=dict)


@dataclass
class QualityEvaluationResult:
    """Aggregated quality evaluation result."""
    overall_score: float
    metrics: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
