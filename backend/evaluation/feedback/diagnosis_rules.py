"""Deterministic quality diagnosis rules for the feedback loop (V1)."""

from __future__ import annotations


SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


# Severity reflects how dangerous the failure mode is for downstream
# strategy/report quality. Historical-evidence misuse, invalid references,
# and semantic over-inference are treated as "high"; reasoning density is
# "medium" because a low density alone does not always produce a bad
# conclusion.
_RULES = [
    {
        "metric": "temporal_compliance",
        "threshold": 80,
        "severity": "high",
        "problem": "历史证据被用于当前状态判断",
        "cause": "historical/stale evidence进入当前竞争判断",
        "suggestion": "强化temporal_level约束",
    },
    {
        "metric": "evidence_integrity",
        "threshold": 90,
        "severity": "high",
        "problem": "存在无效证据引用",
        "cause": "insight/recommendation引用了不存在的evidence_id",
        "suggestion": "增加evidence reference校验",
    },
    {
        "metric": "reasoning_quality",
        "threshold": 80,
        "severity": "medium",
        "problem": "推理链质量不足",
        "cause": "hypothesis evidence density不足",
        "suggestion": "降低high confidence hypothesis比例",
    },
    {
        "metric": "semantic_reasoning",
        "threshold": 70,
        "severity": "high",
        "problem": "存在语义过度推断",
        "cause": "evidence逻辑支撑不足导致过度推断",
        "suggestion": "增加hypothesis审查",
    },
]


def _get_score(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, dict):
        return value.get("score")
    return getattr(value, "score", None)


def diagnose(metrics: dict) -> list[dict]:
    """Map metric scores to an ordered list of quality issues.

    Missing metrics are skipped, so an absent optional semantic_reasoning
    metric does not trigger a false positive.
    """
    issues: list[dict] = []
    for rule in _RULES:
        score = _get_score(metrics.get(rule["metric"]))
        if score is None:
            continue
        if score < rule["threshold"]:
            issues.append(
                {
                    "metric": rule["metric"],
                    "severity": rule["severity"],
                    "problem": rule["problem"],
                    "cause": rule["cause"],
                    "suggestion": rule["suggestion"],
                }
            )
    issues.sort(key=lambda i: SEVERITY_RANK.get(i["severity"], 3))
    return issues
