"""Compare baseline and current score reports."""

from __future__ import annotations

from typing import Any


def _delta(before: float, after: float) -> float:
    return round(after - before, 3)


def _metric_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    return {
        "before": round(float(before), 3),
        "after": round(float(after), 3),
        "delta": _delta(float(before), float(after)),
    }


def compare_score_reports(
    baseline: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    """Compare two score reports at overall, metric, and case level."""

    baseline_cases = baseline.get("cases", [])
    current_cases = current.get("cases", [])

    metric_keys: set[str] = set()
    for case in baseline_cases + current_cases:
        metric_keys.update(case.get("metrics", {}).keys())

    baseline_case_map = {case["case_id"]: case for case in baseline_cases}
    current_case_map = {case["case_id"]: case for case in current_cases}
    all_case_ids = sorted(set(baseline_case_map) | set(current_case_map))

    metric_comparison: dict[str, Any] = {}
    for metric in sorted(metric_keys):
        before_values = [
            case["metrics"][metric]
            for case in baseline_cases
            if metric in case.get("metrics", {})
        ]
        after_values = [
            case["metrics"][metric]
            for case in current_cases
            if metric in case.get("metrics", {})
        ]
        before_avg = sum(before_values) / len(before_values) if before_values else 0.0
        after_avg = sum(after_values) / len(after_values) if after_values else 0.0
        metric_comparison[metric] = _metric_delta(before_avg, after_avg)

    case_comparison: dict[str, Any] = {}
    for case_id in all_case_ids:
        before = baseline_case_map.get(case_id, {}).get("total_score", 0.0)
        after = current_case_map.get(case_id, {}).get("total_score", 0.0)
        case_comparison[case_id] = _metric_delta(float(before), float(after))

    return {
        "overall_score": _metric_delta(
            baseline.get("average_score", 0.0),
            current.get("average_score", 0.0),
        ),
        "metrics": metric_comparison,
        "cases": case_comparison,
    }
