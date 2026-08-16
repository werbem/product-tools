"""Evidence referential integrity metrics (V1.2).

Checks whether insight/recommendation reference IDs actually point to real
evidence, catching hallucinated / dangling references.
"""

from __future__ import annotations

from evaluation.models import MetricResult


def _evidence_ids(evidence_items: list[dict]) -> set[str]:
    ids: set[str] = set()
    for e in evidence_items:
        eid = e.get("id", "") or e.get("source_id", "")
        if eid:
            ids.add(str(eid))
    return ids


def _has_valid_ref(obj: dict, evidence_ids: set[str]) -> bool:
    """True if the object has >=1 valid evidence/cluster/insight reference."""
    if any(str(r) in evidence_ids for r in (obj.get("evidence_refs", []) or [])):
        return True
    if len(obj.get("cluster_refs", []) or []) > 0:
        return True
    if len(obj.get("insight_refs", []) or []) > 0:
        return True
    return False


def evidence_reference_integrity(
    evidence_items: list[dict],
    insights: list[dict],
    recommendations: list[dict],
) -> MetricResult:
    """Metric 1: valid_refs / total_refs across insight+recommendation evidence_refs."""
    evidence_ids = _evidence_ids(evidence_items)
    total_refs = 0
    valid_refs = 0
    invalid_refs: list[str] = []

    for obj in list(insights) + list(recommendations):
        for ref in (obj.get("evidence_refs", []) or []):
            total_refs += 1
            if str(ref) in evidence_ids:
                valid_refs += 1
            else:
                invalid_refs.append(str(ref))

    score = 100.0 if total_refs == 0 else round(valid_refs / total_refs * 100, 2)
    return MetricResult(
        score,
        {
            "total_refs": total_refs,
            "valid_refs": valid_refs,
            "invalid_refs": invalid_refs,
        },
    )


def insight_traceability_integrity(
    evidence_items: list[dict],
    insights: list[dict],
) -> MetricResult:
    """Metric 2: valid_insights / total_insights."""
    evidence_ids = _evidence_ids(evidence_items)
    total = len(insights)
    if total == 0:
        return MetricResult(100.0, {"total": 0, "valid": 0})
    valid = sum(1 for ins in insights if _has_valid_ref(ins, evidence_ids))
    score = round(valid / total * 100, 2)
    return MetricResult(score, {"total": total, "valid": valid})


def strategy_reference_integrity(
    evidence_items: list[dict],
    recommendations: list[dict],
) -> MetricResult:
    """Metric 3: valid_recommendations / total_recommendations."""
    evidence_ids = _evidence_ids(evidence_items)
    total = len(recommendations)
    if total == 0:
        return MetricResult(100.0, {"total": 0, "valid": 0})
    valid = sum(1 for rec in recommendations if _has_valid_ref(rec, evidence_ids))
    score = round(valid / total * 100, 2)
    return MetricResult(score, {"total": total, "valid": valid})
