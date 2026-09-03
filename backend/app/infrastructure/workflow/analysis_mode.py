"""Analysis mode budgets for workflow stages.

Each ``*_timeout_s`` value is a **per-node hard budget** enforced at the workflow
node layer (``asyncio.wait_for``). They are **not** meant to be summed into a
total pipeline duration — stages run sequentially and may finish under budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

AnalysisMode = Literal["fast", "full"]


@dataclass(frozen=True)
class AnalysisModeConfig:
    mode: AnalysisMode
    plan_timeout_s: float
    research_timeout_s: float
    compare_timeout_s: float
    insight_timeout_s: float
    strategy_timeout_s: float
    report_timeout_s: float
    review_timeout_s: float
    skip_insight: bool
    skip_strategy: bool
    skip_review: bool
    skip_compare: bool
    skip_evidence_evaluation: bool
    max_source_types: int
    research_max_results: int
    report_segment_timeout_s: float
    max_evidence_items: int
    max_evaluated_items: int
    compare_max_evidence_items: int
    mode_total_budget_s: float
    clustering_timeout_s: float
    # Step 42: evidence age window + light date enrichment
    evidence_max_age_months: int
    max_undated_evidence_items: int
    enable_lightweight_date_enrichment: bool
    date_enrichment_timeout_s: float
    date_enrichment_max_urls: int


_FAST = AnalysisModeConfig(
    mode="fast",
    plan_timeout_s=30.0,
    research_timeout_s=120.0,
    compare_timeout_s=120.0,
    insight_timeout_s=0.0,
    strategy_timeout_s=0.0,
    report_timeout_s=180.0,
    review_timeout_s=0.0,
    skip_insight=True,
    skip_strategy=True,
    skip_review=True,
    skip_compare=True,
    skip_evidence_evaluation=True,
    max_source_types=1,
    research_max_results=4,
    report_segment_timeout_s=55.0,
    max_evidence_items=999,
    max_evaluated_items=0,
    compare_max_evidence_items=12,
    mode_total_budget_s=360.0,
    clustering_timeout_s=0.0,
    evidence_max_age_months=48,
    max_undated_evidence_items=5,
    enable_lightweight_date_enrichment=True,
    date_enrichment_timeout_s=2.5,
    date_enrichment_max_urls=8,
)

_FULL = AnalysisModeConfig(
    mode="full",
    plan_timeout_s=40.0,
    research_timeout_s=180.0,
    compare_timeout_s=90.0,
    insight_timeout_s=90.0,
    strategy_timeout_s=90.0,
    report_timeout_s=150.0,
    review_timeout_s=60.0,
    skip_insight=False,
    skip_strategy=False,
    skip_review=False,
    skip_compare=False,
    skip_evidence_evaluation=False,
    max_source_types=3,
    research_max_results=4,
    report_segment_timeout_s=55.0,
    max_evidence_items=15,
    max_evaluated_items=10,
    compare_max_evidence_items=12,
    mode_total_budget_s=720.0,
    clustering_timeout_s=60.0,
    evidence_max_age_months=48,
    max_undated_evidence_items=5,
    enable_lightweight_date_enrichment=True,
    date_enrichment_timeout_s=2.5,
    date_enrichment_max_urls=8,
)


def normalize_analysis_mode(value: str | None) -> AnalysisMode:
    mode = (value or "fast").strip().lower()
    return "full" if mode == "full" else "fast"


def get_mode_config(mode: str | None) -> AnalysisModeConfig:
    return _FULL if normalize_analysis_mode(mode) == "full" else _FAST


def resolve_analysis_mode(state: dict[str, Any]) -> AnalysisMode:
    user_input = state.get("user_input") or {}
    optional = user_input.get("optional") if isinstance(user_input, dict) else None
    if isinstance(optional, dict) and optional.get("analysis_mode"):
        return normalize_analysis_mode(str(optional.get("analysis_mode")))
    if isinstance(user_input, dict) and user_input.get("analysis_mode"):
        return normalize_analysis_mode(str(user_input.get("analysis_mode")))
    return "fast"


def resolve_mode_config(state: dict[str, Any]) -> AnalysisModeConfig:
    return get_mode_config(resolve_analysis_mode(state))


def effective_research_timeout_s(cfg: AnalysisModeConfig, state: dict[str, Any]) -> float:
    """Research budget for a workflow run (may shrink for MCP collection)."""
    optional = (state.get("user_input") or {}).get("optional") or {}
    if optional.get("workflow_kind") == "intelligence_collection":
        # MCP collect outer budget is 120s; leave headroom for plan + finalize.
        return min(cfg.research_timeout_s, 80.0)
    return cfg.research_timeout_s


def effective_plan_timeout_s(cfg: AnalysisModeConfig, state: dict[str, Any]) -> float:
    optional = (state.get("user_input") or {}).get("optional") or {}
    if optional.get("workflow_kind") == "intelligence_collection":
        return min(cfg.plan_timeout_s, 25.0)
    return cfg.plan_timeout_s


FAST_MAX_PLAN_DIMENSIONS = 2


def trim_research_plan_for_mode(plan: dict[str, Any], cfg: AnalysisModeConfig) -> dict[str, Any]:
    """Fast mode: cap analysis_scope to 1–2 dimensions to shrink Research scope."""
    if cfg.mode != "fast":
        return plan
    trimmed = dict(plan)
    scope = list(trimmed.get("analysis_scope") or [])
    if len(scope) > FAST_MAX_PLAN_DIMENSIONS:
        trimmed["analysis_scope"] = scope[:FAST_MAX_PLAN_DIMENSIONS]
    return trimmed
