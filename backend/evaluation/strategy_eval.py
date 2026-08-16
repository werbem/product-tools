"""Strategy traceability metrics."""

from __future__ import annotations

from evaluation.models import MetricResult


def strategy_traceability(recommendations: list[dict]) -> MetricResult:
    """Metric 4: traceable_recommendations / total_recommendations (0-100).

    A recommendation is traceable if it has evidence_refs or cluster_refs.
    """
    total = len(recommendations)
    if total == 0:
        return MetricResult(100.0, {"total": 0, "traceable": 0, "untraceable": 0})

    traceable = 0
    untraceable_actions: list[str] = []
    for rec in recommendations:
        ev = len(rec.get("evidence_refs", []) or [])
        cl = len(rec.get("cluster_refs", []) or [])
        if ev > 0 or cl > 0:
            traceable += 1
        else:
            untraceable_actions.append((rec.get("action", "") or "")[:60])

    untraceable = total - traceable
    score = round(traceable / total * 100, 2)
    return MetricResult(
        score,
        {
            "total": total,
            "traceable": traceable,
            "untraceable": untraceable,
            "untraceable_actions": untraceable_actions,
        },
    )
