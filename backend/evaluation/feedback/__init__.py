"""Analysis Quality Feedback Loop V1.

Turns a QualityEvaluationResult into a quality diagnosis, improvement
suggestions, and generation constraints. Offline tooling only; it never
mutates production prompts, rules, DTOs, or the generation workflow.
"""

from evaluation.feedback.quality_feedback import (
    QualityFeedbackResult,
    evaluate_feedback,
)

__all__ = [
    "QualityFeedbackResult",
    "evaluate_feedback",
]
