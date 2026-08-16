"""Insight quality metrics (evidence coverage + quality distribution)."""

from __future__ import annotations

from evaluation.models import MetricResult


def _is_supported(insight: dict) -> bool:
    """Whether an insight has evidence support."""
    insight_type = insight.get("type", "")
    ev = len(insight.get("evidence_refs", []) or [])
    cl = len(insight.get("cluster_refs", []) or [])
    if insight_type == "fact":
        return ev > 0 or cl > 0
    # hypothesis / observation / unknown
    return ev + cl >= 1


def insight_evidence_coverage(insights: list[dict]) -> MetricResult:
    """Metric 2: supported_insights / total_insights (0-100)."""
    total = len(insights)
    if total == 0:
        return MetricResult(100.0, {"total": 0, "supported": 0, "unsupported": 0})
    supported = sum(1 for i in insights if _is_supported(i))
    unsupported = total - supported
    score = round(supported / total * 100, 2)
    return MetricResult(
        score,
        {"total": total, "supported": supported, "unsupported": unsupported},
    )


def insight_quality_distribution(insights: list[dict]) -> MetricResult:
    """Metric 3: confidence + type distribution (diagnostic, no score)."""
    total = len(insights)
    conf_dist: dict[str, int] = {}
    type_dist: dict[str, int] = {}
    for i in insights:
        c = i.get("confidence", "medium") or "medium"
        conf_dist[c] = conf_dist.get(c, 0) + 1
        t = i.get("type", "") or "unknown"
        type_dist[t] = type_dist.get(t, 0) + 1

    high_hyp = sum(
        1 for i in insights
        if i.get("type") == "hypothesis" and i.get("confidence") == "high"
    )
    over_generation_ratio = round(high_hyp / total, 3) if total else 0.0

    return MetricResult(
        None,
        {
            "total": total,
            "confidence_distribution": conf_dist,
            "type_distribution": type_dist,
            "fact_count": type_dist.get("fact", 0),
            "observation_count": type_dist.get("observation", 0),
            "hypothesis_count": type_dist.get("hypothesis", 0),
            "high_confidence_hypothesis_ratio": over_generation_ratio,
        },
    )
