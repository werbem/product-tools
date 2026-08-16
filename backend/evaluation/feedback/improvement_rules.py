"""Map diagnosed issues to generation constraints (V1).

These constraints are advisory output only. They are never applied to
production prompts or rules automatically.
"""

from __future__ import annotations


_CONSTRAINTS = {
    "temporal_compliance": {
        "target": "ReportAgent",
        "rule": "historical evidence只能用于背景描述",
    },
    "evidence_integrity": {
        "target": "InsightAgent",
        "rule": "所有insight必须引用真实evidence_id",
    },
    "reasoning_quality": {
        "target": "InsightAgent",
        "rule": "high confidence hypothesis必须满足 evidence_count>=2",
    },
    "semantic_reasoning": {
        "target": "StrategyAgent",
        "rule": "recommendation必须区分fact和hypothesis",
    },
}


def build_generation_constraints(issues: list[dict]) -> list[dict]:
    """Derive deduplicated generation constraints from diagnosed issues."""
    constraints: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for issue in issues:
        spec = _CONSTRAINTS.get(issue.get("metric", ""))
        if not spec:
            continue
        key = (spec["target"], spec["rule"])
        if key in seen:
            continue
        seen.add(key)
        constraints.append({"target": spec["target"], "rule": spec["rule"]})
    return constraints
