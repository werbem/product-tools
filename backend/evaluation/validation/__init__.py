"""Production Quality Validation V1 (offline).

Compares before/after report versions using the existing quality evaluation
layer and emits a validation report, summary, and regression findings. No
agents, workflow nodes, DTOs, or prompts are modified.
"""

from evaluation.validation.validation import (
    METRICS,
    build_summary,
    compare_before_after,
    discover_cases,
    evaluate_state,
    has_quality_score,
    run_validation,
)

__all__ = [
    "METRICS",
    "evaluate_state",
    "has_quality_score",
    "discover_cases",
    "compare_before_after",
    "build_summary",
    "run_validation",
]
