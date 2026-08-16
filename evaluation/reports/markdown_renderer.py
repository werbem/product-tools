"""Render evaluation report.json into Markdown."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def render_markdown(report: dict[str, Any]) -> str:
    """Render a report dictionary as Markdown."""

    summary = report.get("summary", {})
    metrics = report.get("metrics", {})
    failures = report.get("failures", [])
    cases = report.get("cases", [])

    lines = [
        "# Evaluation Report",
        "",
        "## Evaluation Summary",
        "",
        f"- Total Cases: {summary.get('total_cases', 0)}",
        f"- Passed Cases: {summary.get('passed_cases', 0)}",
        f"- Average Score: {summary.get('average_score', 0.0)}",
        "",
        "## Metric Overview",
        "",
    ]

    for section, title in [
        ("collection_metrics", "Collection Metrics"),
        ("analysis_metrics", "Analysis Metrics"),
        ("mcp_metrics", "MCP Metrics"),
    ]:
        lines.append(f"### {title}")
        lines.append("")
        lines.append("| Metric | Score |")
        lines.append("|---|---:|")
        for metric, score in metrics.get(section, {}).items():
            lines.append(f"| {metric} | {score} |")
        lines.append("")

    lines.extend([
        "## Case Detail",
        "",
    ])
    for case in cases:
        lines.append(f"### {case.get('case_id', 'unknown')}")
        lines.append(f"- Total Score: {case.get('total_score', 0.0)}")
        lines.append("")

    lines.extend([
        "## Failure Cases",
        "",
    ])
    if failures:
        lines.extend(f"- {case_id}" for case_id in failures)
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def render_markdown_file(
    report_path: Path,
    output_path: Path,
) -> str:
    """Load report.json and write report.md."""

    report = json.loads(report_path.read_text(encoding="utf-8"))
    markdown = render_markdown(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return markdown
