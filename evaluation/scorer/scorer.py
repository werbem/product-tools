"""Unified rule-based scorer entrypoint."""

from __future__ import annotations

from typing import Any

from evaluation.scorer.analysis_scorer import score_analysis
from evaluation.scorer.collection_scorer import score_collection
from evaluation.scorer.mcp_scorer import score_mcp


def score_case(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    tool = result.get("tool") or case.get("tool", "")
    if tool in {"collect", "collect_competitor_intelligence"}:
        domain_metrics = score_collection(case, result)
    elif tool in {"analyze", "analyze_competition"}:
        domain_metrics = score_analysis(case, result)
    else:
        raise ValueError(f"unsupported tool: {tool}")

    mcp_metrics = score_mcp(result)
    total_score = round(
        (domain_metrics["total_score"] + mcp_metrics["total_score"]) / 2,
        3,
    )
    return {
        "case_id": result.get("case_id"),
        "total_score": total_score,
        "metrics": {
            **domain_metrics,
            **mcp_metrics,
        },
    }


def score_report(
    cases: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> dict[str, Any]:
    case_map = {case["case_id"]: case for case in cases}
    scored = [score_case(case_map[result["case_id"]], result) for result in results]
    average_score = round(
        sum(item["total_score"] for item in scored) / len(scored)
        if scored
        else 0.0,
        3,
    )
    failure_cases = [
        result["case_id"] for result in results if result["status"] != "passed"
    ]
    return {
        "average_score": average_score,
        "cases": scored,
        "failure_cases": failure_cases,
    }
