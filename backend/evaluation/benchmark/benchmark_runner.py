"""Benchmark runner + quality trend analysis (V1)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from evaluation.benchmark.models import (
    BenchmarkResult,
    QualityTrend,
    metric_score,
    result_as_dict,
)
from evaluation.benchmark.regression import detect_regression


def _check_constraint(value, constraint) -> bool:
    if value is None:
        return False
    text = str(constraint).strip()
    m = re.match(r"^(<=|>=|==|!=|<|>)\s*(-?\d+(?:\.\d+)?)$", text)
    if m:
        op, num = m.group(1), float(m.group(2))
        if op == "<":
            return value < num
        if op == "<=":
            return value <= num
        if op == ">":
            return value > num
        if op == ">=":
            return value >= num
        if op == "==":
            return value == num
        if op == "!=":
            return value != num
    m = re.match(r"^range:\s*(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)$", text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        return lo <= value <= hi
    return False


def _check_expected(result: dict, expected: dict) -> bool:
    if not expected:
        return True
    metrics = result.get("metrics", {}) or {}
    for metric, constraint in expected.items():
        if not _check_constraint(metric_score(metrics.get(metric)), constraint):
            return False
    return True


def load_cases(directory) -> list[dict]:
    """Recursively load JSON benchmark cases from a directory tree."""
    root = Path(directory)
    cases: list[dict] = []
    for p in sorted(root.rglob("*.json")):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, dict):
            cases.append(data)
    return cases


def run_benchmark(cases, evaluate_fn=None) -> BenchmarkResult:
    """Run benchmark cases and report pass/fail plus regression detection."""
    if evaluate_fn is None:
        from evaluation.quality_evaluator import evaluate as evaluate_fn

    total = len(cases)
    passed = 0
    failed = 0
    findings = []
    for case in cases:
        result = result_as_dict(evaluate_fn(case.get("input")))
        ok = _check_expected(result, case.get("expected", {}))
        if "baseline" in case:
            regressions = detect_regression(result, result_as_dict(case["baseline"]))
            if regressions:
                findings.extend(regressions)
                ok = False
        if ok:
            passed += 1
        else:
            failed += 1
    return BenchmarkResult(
        total=total,
        passed=passed,
        failed=failed,
        regression_detected=bool(findings),
        findings=findings,
    )


def _trend(scores: list[float]) -> str:
    if len(scores) < 2:
        return "stable"
    if scores[-1] > scores[0]:
        return "improving"
    if scores[-1] < scores[0]:
        return "declining"
    return "stable"


def _fmt_delta(delta: float) -> str:
    if delta == int(delta):
        return f"{int(delta):+d}"
    return f"{delta:+.2f}"


def _collect_metric_keys(snapshots) -> list[str]:
    keys: set[str] = set()
    for s in snapshots:
        metrics = s.get("metrics", {}) or {}
        if isinstance(metrics, dict):
            keys.update(metrics.keys())
    return sorted(keys)


def calculate_quality_trend(snapshots, n=None, metric_keys=None) -> QualityTrend:
    """Compute overall and per-metric trend across the last N snapshots."""
    snaps = [result_as_dict(s) for s in snapshots]
    if n is not None:
        snaps = snaps[-n:]

    overall_scores = [
        s.get("overall_score") for s in snaps
    ]
    overall_scores = [v for v in overall_scores if isinstance(v, (int, float))]
    average = (
        round(sum(overall_scores) / len(overall_scores), 2)
        if overall_scores
        else 0.0
    )

    keys = metric_keys if metric_keys is not None else _collect_metric_keys(snaps)
    metric_trends: dict[str, str] = {}
    for key in keys:
        values = [
            metric_score(s.get("metrics", {}).get(key)) for s in snaps
        ]
        values = [v for v in values if isinstance(v, (int, float))]
        if len(values) >= 2:
            metric_trends[f"{key}_trend"] = _fmt_delta(
                round(values[-1] - values[0], 2)
            )
        else:
            metric_trends[f"{key}_trend"] = "0"

    return QualityTrend(
        trend=_trend(overall_scores),
        average_score=average,
        metric_trends=metric_trends,
    )
