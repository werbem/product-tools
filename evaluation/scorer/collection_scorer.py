"""Rule-based collection metrics."""

from __future__ import annotations

from typing import Any


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _evidence_quality_score(item: dict[str, Any]) -> float:
    score = 0.0
    if item.get("finding"):
        score += 0.5
    if item.get("confidence"):
        score += 0.25
    if item.get("quality") is not None:
        score += 0.25
    return score


def _source_quality_score(item: dict[str, Any]) -> float:
    source = item.get("source") or {}
    score = 0.0
    if source.get("name"):
        score += 0.4
    if source.get("type"):
        score += 0.3
    if source.get("url"):
        score += 0.3
    return score


def score_collection(case: dict[str, Any], result: dict[str, Any]) -> dict[str, float]:
    expected = case.get("expected", result.get("expected", {}))
    required_dimensions = expected.get("required_dimensions", [])
    output = result.get("output", {})
    coverage = output.get("coverage") or {}
    by_dimension = coverage.get("by_dimension") or {}
    evidence_items = output.get("evidenceItem") or []

    if required_dimensions:
        covered = sum(
            1 for dimension in required_dimensions
            if int(by_dimension.get(dimension, 0) or 0) > 0
        )
        coverage_score = covered / len(required_dimensions)
    else:
        coverage_score = 1.0 if evidence_items else 0.0

    evidence_quality_score = _mean(
        [_evidence_quality_score(item) for item in evidence_items]
    )
    source_quality_score = _mean(
        [_source_quality_score(item) for item in evidence_items]
    )

    total_score = round(
        _mean([coverage_score, evidence_quality_score, source_quality_score]),
        3,
    )
    return {
        "coverage_score": round(coverage_score, 3),
        "evidence_quality_score": round(evidence_quality_score, 3),
        "source_quality_score": round(source_quality_score, 3),
        "total_score": total_score,
    }
