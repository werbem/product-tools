"""Quality evaluator orchestrator + input adapter."""

from __future__ import annotations

import json

from evaluation.models import QualityEvaluationResult
from evaluation.insight_eval import (
    insight_evidence_coverage,
    insight_quality_distribution,
)
from evaluation.strategy_eval import strategy_traceability
from evaluation.temporal_eval import evidence_freshness, temporal_compliance
from evaluation.evidence_eval import (
    evidence_reference_integrity,
    insight_traceability_integrity,
    strategy_reference_integrity,
)
from evaluation.reasoning_eval import insight_reasoning_score
from evaluation.semantic_eval import SemanticReasoningEvaluator


def normalize_report_input(data) -> dict:
    """Adapter: normalize various input shapes to a canonical structure.

    Accepts:
      - a JSON file path (report_result.json)
      - a dict with keys such as evidence_bundle / insights /
        gap_analysis / strategic_insights / report_document / markdown

    Returns:
      {"evidence_items": [...], "insights": [...],
       "recommendations": [...], "markdown": "..."}
    """
    if isinstance(data, str):
        with open(data, encoding="utf-8") as f:
            data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("input must be a dict or a JSON file path")

    # evidence items
    evidence_items: list[dict] = []
    eb = data.get("evidence_bundle") or {}
    if isinstance(eb, dict):
        evidence_items = eb.get("evidence_items", []) or []
    elif isinstance(eb, list):
        evidence_items = eb
    if not evidence_items and isinstance(data.get("evidence_sources"), list):
        # reports.json shape: source_id -> id
        evidence_items = [
            {**s, "id": s.get("source_id", "")}
            for s in data["evidence_sources"]
            if isinstance(s, dict)
        ]

    # insights
    ins = data.get("insights") or {}
    if isinstance(ins, dict):
        insights = ins.get("insights", []) or []
    elif isinstance(ins, list):
        insights = ins
    else:
        insights = []

    # recommendations
    si = data.get("strategic_insights") or {}
    recommendations = si.get("recommendations", []) if isinstance(si, dict) else []

    # markdown
    markdown = data.get("markdown", "") or ""
    if not markdown:
        rd = data.get("report_document") or data.get("report") or {}
        if isinstance(rd, dict):
            formats = rd.get("formats", {}) or {}
            markdown = formats.get("markdown", "") if isinstance(formats, dict) else ""

    return {
        "evidence_items": evidence_items,
        "insights": insights,
        "recommendations": recommendations,
        "markdown": markdown,
    }


def evaluate(normalized_input: dict) -> QualityEvaluationResult:
    """Compute all metrics and aggregate an overall score."""
    evidence_items = normalized_input.get("evidence_items", []) or []
    insights = normalized_input.get("insights", []) or []
    recommendations = normalized_input.get("recommendations", []) or []
    markdown = normalized_input.get("markdown", "") or ""

    coverage = insight_evidence_coverage(insights)
    distribution = insight_quality_distribution(insights)
    traceability = strategy_traceability(recommendations)
    freshness = evidence_freshness(evidence_items)
    temporal = temporal_compliance(
        evidence_items, insights, recommendations, markdown
    )
    ref_integrity = evidence_reference_integrity(
        evidence_items, insights, recommendations
    )
    insight_integrity = insight_traceability_integrity(evidence_items, insights)
    strategy_integrity = strategy_reference_integrity(
        evidence_items, recommendations
    )
    integrity_score = round(
        (ref_integrity.score + insight_integrity.score + strategy_integrity.score) / 3,
        2,
    )
    reasoning = insight_reasoning_score(insights)

    metrics = {
        "temporal_compliance": {
            "score": temporal.score,
            "details": temporal.details,
        },
        "insight_evidence_coverage": {
            "score": coverage.score,
            "details": coverage.details,
        },
        "strategy_traceability": {
            "score": traceability.score,
            "details": traceability.details,
        },
        "freshness": {
            "score": freshness.score,
            "details": freshness.details,
        },
        "insight_quality_distribution": {
            "details": distribution.details,
        },
        "evidence_integrity": {
            "score": integrity_score,
            "details": {
                "evidence_reference_integrity": ref_integrity.score,
                "total_refs": ref_integrity.details["total_refs"],
                "valid_refs": ref_integrity.details["valid_refs"],
                "invalid_refs": ref_integrity.details["invalid_refs"],
                "insight_traceability_integrity": insight_integrity.score,
                "insight_total": insight_integrity.details["total"],
                "insight_valid": insight_integrity.details["valid"],
                "strategy_reference_integrity": strategy_integrity.score,
                "strategy_total": strategy_integrity.details["total"],
                "strategy_valid": strategy_integrity.details["valid"],
            },
        },
        "reasoning_quality": {
            "score": reasoning.score,
            "details": reasoning.details,
        },
    }

    scored = [
        m["score"]
        for key in (
            "temporal_compliance",
            "insight_evidence_coverage",
            "strategy_traceability",
            "freshness",
            "evidence_integrity",
            "reasoning_quality",
        )
        for m in [metrics[key]]
        if m["score"] is not None
    ]
    overall = round(sum(scored) / len(scored), 2) if scored else 0.0

    warnings: list[str] = list(
        temporal.details.get("markdown_warnings", [])
    )
    ratio = distribution.details.get("high_confidence_hypothesis_ratio", 0)
    if ratio > 0.5:
        warnings.append(
            f"高置信假设占比过高（{ratio:.0%}），存在过度推断风险"
        )

    return QualityEvaluationResult(
        overall_score=overall,
        metrics=metrics,
        warnings=warnings,
    )


def _recompute_overall(metrics: dict) -> float:
    scored = [
        m["score"]
        for m in metrics.values()
        if isinstance(m, dict) and m.get("score") is not None
    ]
    return round(sum(scored) / len(scored), 2) if scored else 0.0


async def evaluate_async(
    normalized_input: dict,
    llm_client=None,
    max_insights: int = 5,
) -> QualityEvaluationResult:
    """Deterministic metrics + optional offline semantic reasoning critic.

    `semantic_reasoning` is the only metric that may call an LLM. When no LLM
    client is available (or every evaluation fails) it is omitted, so the
    surrounding pipeline never breaks.
    """
    result = evaluate(normalized_input)
    evaluator = SemanticReasoningEvaluator(
        llm_client=llm_client, max_insights=max_insights
    )
    semantic = await evaluator.evaluate(normalized_input)
    if semantic is not None and semantic.score is not None:
        result.metrics["semantic_reasoning"] = {
            "score": semantic.score,
            "details": semantic.details,
        }
        result.overall_score = _recompute_overall(result.metrics)
    return result


def evaluate_with_semantic(
    normalized_input: dict,
    llm_client=None,
    max_insights: int = 5,
) -> QualityEvaluationResult:
    """Sync convenience wrapper around :func:`evaluate_async`."""
    import asyncio

    return asyncio.run(
        evaluate_async(
            normalized_input,
            llm_client=llm_client,
            max_insights=max_insights,
        )
    )
