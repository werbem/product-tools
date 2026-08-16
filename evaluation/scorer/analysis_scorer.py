"""Rule-based analysis metrics."""

from __future__ import annotations

from typing import Any


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _recommendation_score(recommendation: dict[str, Any]) -> float:
    has_action = bool(recommendation.get("action"))
    has_object = any(
        recommendation.get(key)
        for key in ("object", "objective", "expected_value")
    )
    has_reason = any(
        recommendation.get(key)
        for key in ("reason", "rationale")
    )
    return sum([has_action, has_object, has_reason]) / 3


def score_analysis(case: dict[str, Any], result: dict[str, Any]) -> dict[str, float]:
    output = result.get("output", {})
    comparison = output.get("comparison") or {}
    advantages = output.get("advantages") or []
    gaps = output.get("gaps") or []
    recommendations = output.get("recommendations") or []

    completeness_score = sum(
        bool(value) for value in [comparison, advantages, gaps, recommendations]
    ) / 4

    insight_quality_score = (
        0.5 * bool(comparison)
        + 0.5 * bool(gaps or advantages)
    )

    recommendation_score = _mean(
        [_recommendation_score(item) for item in recommendations]
    )

    total_score = round(
        _mean([completeness_score, insight_quality_score, recommendation_score]),
        3,
    )
    return {
        "completeness_score": round(completeness_score, 3),
        "insight_quality_score": round(insight_quality_score, 3),
        "recommendation_score": round(recommendation_score, 3),
        "total_score": total_score,
    }
