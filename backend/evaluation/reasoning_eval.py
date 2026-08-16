"""Insight reasoning quality metrics (V1.3)."""

from __future__ import annotations

from evaluation.models import MetricResult


def _evidence_count(insight: dict) -> int:
    return len(insight.get("evidence_refs", []) or []) + len(
        insight.get("cluster_refs", []) or []
    )


def fact_confidence_consistency(insights: list[dict]) -> MetricResult:
    """Metric 1: valid_high_facts / total_high_facts (0-100)."""
    high_facts = [
        i for i in insights
        if i.get("type") == "fact" and i.get("confidence") == "high"
    ]
    total = len(high_facts)
    if total == 0:
        return MetricResult(100.0, {"total_high_facts": 0, "valid_high_facts": 0})
    valid = sum(1 for f in high_facts if _evidence_count(f) >= 1)
    score = round(valid / total * 100, 2)
    return MetricResult(
        score,
        {"total_high_facts": total, "valid_high_facts": valid},
    )


def hypothesis_evidence_density(insights: list[dict]) -> MetricResult:
    """Metric 2: average per-hypothesis density score (0-100)."""
    hyps = [i for i in insights if i.get("type") == "hypothesis"]
    total = len(hyps)
    if total == 0:
        return MetricResult(100.0, {"total_hypotheses": 0, "density_distribution": {}})

    dist = {"acceptable": 0, "weak": 0, "invalid": 0}
    scores: list[int] = []
    for h in hyps:
        cnt = _evidence_count(h)
        if cnt >= 2:
            scores.append(100)
            dist["acceptable"] += 1
        elif cnt == 1:
            scores.append(50)
            dist["weak"] += 1
        else:
            scores.append(0)
            dist["invalid"] += 1

    score = round(sum(scores) / total, 2)
    return MetricResult(
        score,
        {"total_hypotheses": total, "density_distribution": dist},
    )


def high_confidence_hypothesis_ratio(insights: list[dict]) -> float:
    """Metric 3: high_confidence_hypothesis / all_hypothesis (diagnostic)."""
    hyps = [i for i in insights if i.get("type") == "hypothesis"]
    total = len(hyps)
    if total == 0:
        return 0.0
    high = sum(1 for h in hyps if h.get("confidence") == "high")
    return round(high / total, 3)


def _penalty_score(ratio: float) -> float:
    """High-confidence hypothesis over-generation penalty (0-100)."""
    if ratio <= 0.30:
        return 100.0
    if ratio <= 0.60:
        return 70.0
    return 40.0


def insight_reasoning_score(insights: list[dict]) -> MetricResult:
    """Metric 4: 0.4*fact + 0.4*hypothesis_density + 0.2*penalty."""
    fact = fact_confidence_consistency(insights)
    density = hypothesis_evidence_density(insights)
    ratio = high_confidence_hypothesis_ratio(insights)
    penalty = _penalty_score(ratio)

    score = round(0.4 * fact.score + 0.4 * density.score + 0.2 * penalty, 2)
    return MetricResult(
        score,
        {
            "fact_confidence_consistency": fact.score,
            "hypothesis_density": density.score,
            "high_confidence_hypothesis_ratio": ratio,
            "high_confidence_penalty": penalty,
            "total_high_facts": fact.details["total_high_facts"],
            "valid_high_facts": fact.details["valid_high_facts"],
            "density_distribution": density.details["density_distribution"],
        },
    )
