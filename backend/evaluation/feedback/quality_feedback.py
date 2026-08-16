"""Quality Feedback Loop V1 orchestration.

Input: QualityEvaluationResult (or its dict form).
Output: QualityFeedbackResult with overall health, issues, and generation
constraints. Pure and deterministic; no LLM call.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from evaluation.feedback.diagnosis_rules import diagnose
from evaluation.feedback.improvement_rules import build_generation_constraints


@dataclass
class QualityFeedbackResult:
    overall_health: str
    issues: list = field(default_factory=list)
    generation_constraints: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _overall_health(overall_score: float) -> str:
    if overall_score >= 90:
        return "good"
    if overall_score >= 70:
        return "warning"
    return "poor"


def evaluate_feedback(result) -> QualityFeedbackResult:
    """Convert an evaluation result into quality feedback.

    Accepts either a QualityEvaluationResult object or a dict produced by its
    ``to_dict()``.
    """
    if isinstance(result, dict):
        overall = result.get("overall_score", 0.0) or 0.0
        metrics = result.get("metrics", {}) or {}
    else:
        overall = getattr(result, "overall_score", 0.0) or 0.0
        metrics = getattr(result, "metrics", {}) or {}

    issues = diagnose(metrics)
    constraints = build_generation_constraints(issues)
    return QualityFeedbackResult(
        overall_health=_overall_health(overall),
        issues=issues,
        generation_constraints=constraints,
    )
