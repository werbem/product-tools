"""Version regression detection (V1)."""

from __future__ import annotations

from evaluation.benchmark.models import (
    RegressionFinding,
    metric_score,
    result_as_dict,
)


def _severity(change: float) -> str:
    return "high" if change <= -10 else "medium"


def detect_regression(current, baseline) -> list[RegressionFinding]:
    """Compare a current result against a baseline and return regressions.

    An overall score drop beyond 5 points and any metric drop beyond 5 points
    are both treated as regressions.
    """
    current = result_as_dict(current)
    baseline = result_as_dict(baseline)
    findings: list[RegressionFinding] = []

    cur_overall = current.get("overall_score")
    base_overall = baseline.get("overall_score")
    if cur_overall is not None and base_overall is not None:
        change = round(cur_overall - base_overall, 2)
        if change < -5:
            findings.append(
                RegressionFinding(
                    type="regression",
                    metric="overall_score",
                    change=change,
                    severity=_severity(change),
                )
            )

    cur_metrics = current.get("metrics", {}) or {}
    base_metrics = baseline.get("metrics", {}) or {}
    for metric in sorted(set(cur_metrics) | set(base_metrics)):
        cur = metric_score(cur_metrics.get(metric))
        base = metric_score(base_metrics.get(metric))
        if cur is None or base is None:
            continue
        change = round(cur - base, 2)
        if change < -5:
            findings.append(
                RegressionFinding(
                    type="metric_regression",
                    metric=metric,
                    change=change,
                    severity=_severity(change),
                )
            )

    return findings
