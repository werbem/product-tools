"""Generate a normalized evaluation report from a score report."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


COLLECTION_METRICS = [
    "coverage_score",
    "evidence_quality_score",
    "source_quality_score",
]
ANALYSIS_METRICS = [
    "completeness_score",
    "insight_quality_score",
    "recommendation_score",
]
MCP_METRICS = [
    "latency",
    "latency_score",
    "failure_rate",
    "schema_validation",
]


def _average(cases: list[dict[str, Any]], metric: str) -> float:
    values = [
        float(case["metrics"][metric])
        for case in cases
        if "metrics" in case and metric in case["metrics"]
    ]
    return round(sum(values) / len(values), 3) if values else 0.0


def build_report(score_report: dict[str, Any]) -> dict[str, Any]:
    """Build report.json content from a score report."""

    cases = score_report.get("cases", [])
    failures = score_report.get("failure_cases", [])
    total_cases = len(cases)
    passed_cases = max(0, total_cases - len(failures))

    return {
        "summary": {
            "total_cases": total_cases,
            "passed_cases": passed_cases,
            "average_score": score_report.get("average_score", 0.0),
        },
        "metrics": {
            "collection_metrics": {
                metric: _average(cases, metric)
                for metric in COLLECTION_METRICS
            },
            "analysis_metrics": {
                metric: _average(cases, metric)
                for metric in ANALYSIS_METRICS
            },
            "mcp_metrics": {
                metric: _average(cases, metric)
                for metric in MCP_METRICS
            },
        },
        "failures": failures,
        "cases": cases,
    }


def generate_report(
    score_report_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    """Load score_report.json and write report.json."""

    score_report = json.loads(score_report_path.read_text(encoding="utf-8"))
    report = build_report(score_report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report
