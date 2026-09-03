"""Workflow-level elapsed budget tracking for full/fast mode total caps."""

from __future__ import annotations

import time
from typing import Any

from app.infrastructure.workflow.analysis_mode import AnalysisModeConfig

TOTAL_BUDGET_BUFFER_S = 5.0
HARD_LLM_CUTOFF_S = 720.0
REVIEW_SKIP_ELAPSED_S = 715.0
REPORT_COMPACT_ELAPSED_S = 660.0
STRATEGY_SKIP_ELAPSED_S = 660.0
INSIGHT_SKIP_ELAPSED_S = 630.0
COMPARE_BUDGET_ELAPSED_S = 600.0

# Step 40: reserves so Compare/Strategy leave room for report/review
REPORT_RESERVE_S = 120.0
REVIEW_RESERVE_S = 45.0
BUFFER_RESERVE_S = 20.0
STRATEGY_RESERVE_S = 70.0  # leave room for compact Strategy after Compare
MIN_COMPARE_ATTEMPT_S = 45.0
MIN_STRATEGY_ATTEMPT_S = 45.0
TIGHT_NODE_CAP_S = 60.0
PRIMARY_LLM_FRACTION = 0.78


def workflow_budget_patch(state: dict[str, Any]) -> dict[str, Any]:
    """Ensure monotonic start timestamp exists (set once at first node)."""
    if state.get("workflow_started_at") is not None:
        return {}
    return {"workflow_started_at": time.monotonic()}


def elapsed_s(state: dict[str, Any]) -> float:
    started = state.get("workflow_started_at")
    if started is None:
        return 0.0
    return max(0.0, time.monotonic() - float(started))


def remaining_llm_budget_s(state: dict[str, Any], cfg: AnalysisModeConfig) -> float:
    """Seconds left before the hard LLM cutoff (Full 720s)."""
    budget = float(getattr(cfg, "mode_total_budget_s", 0.0) or 0.0)
    if budget <= 0 or cfg.mode != "full":
        return float("inf")
    return max(0.0, HARD_LLM_CUTOFF_S - elapsed_s(state))


def is_total_budget_exhausted(state: dict[str, Any], cfg: AnalysisModeConfig) -> bool:
    budget = float(getattr(cfg, "mode_total_budget_s", 0.0) or 0.0)
    if budget <= 0:
        return False
    return elapsed_s(state) >= budget - TOTAL_BUDGET_BUFFER_S


def should_block_llm_for_budget(state: dict[str, Any], cfg: AnalysisModeConfig) -> bool:
    """Full mode: no further LLM calls once hard cutoff reached."""
    if cfg.mode != "full":
        return False
    return elapsed_s(state) >= HARD_LLM_CUTOFF_S


def should_skip_compare_for_budget(state: dict[str, Any], cfg: AnalysisModeConfig) -> bool:
    if cfg.mode != "full":
        return False
    return elapsed_s(state) >= COMPARE_BUDGET_ELAPSED_S


def should_skip_insight_for_budget(state: dict[str, Any], cfg: AnalysisModeConfig) -> bool:
    if cfg.mode != "full":
        return False
    return elapsed_s(state) >= INSIGHT_SKIP_ELAPSED_S


def should_skip_strategy_for_budget(state: dict[str, Any], cfg: AnalysisModeConfig) -> bool:
    if cfg.mode != "full":
        return False
    return elapsed_s(state) >= STRATEGY_SKIP_ELAPSED_S


def should_skip_review_for_budget(state: dict[str, Any], cfg: AnalysisModeConfig) -> bool:
    """Full mode: skip Review when elapsed exceeds 715s."""
    if cfg.mode != "full":
        return False
    return elapsed_s(state) >= REVIEW_SKIP_ELAPSED_S


def should_use_compact_report(state: dict[str, Any], cfg: AnalysisModeConfig) -> bool:
    """Full mode: shorten report prompt when elapsed exceeds 660s."""
    if cfg.mode != "full":
        return False
    return elapsed_s(state) >= REPORT_COMPACT_ELAPSED_S


def effective_node_timeout_s(
    state: dict[str, Any],
    cfg: AnalysisModeConfig,
    node_timeout_s: float,
) -> float:
    """Cap per-node timeout by remaining Full-mode LLM budget."""
    if cfg.mode != "full":
        return node_timeout_s
    remaining = remaining_llm_budget_s(state, cfg)
    if remaining <= 0:
        return 0.0
    return min(node_timeout_s, remaining)


def _downstream_reserve_for_compare() -> float:
    return STRATEGY_RESERVE_S + REPORT_RESERVE_S + REVIEW_RESERVE_S + BUFFER_RESERVE_S


def _downstream_reserve_for_strategy() -> float:
    return REPORT_RESERVE_S + REVIEW_RESERVE_S + BUFFER_RESERVE_S


def effective_compare_timeout_s(state: dict[str, Any], cfg: AnalysisModeConfig) -> float:
    """Compare node budget: min(cfg, remaining - strategy/report/review reserve)."""
    base = float(getattr(cfg, "compare_timeout_s", 0.0) or 0.0)
    if cfg.mode != "full":
        return base
    remaining = remaining_llm_budget_s(state, cfg)
    available = remaining - _downstream_reserve_for_compare()
    if available >= MIN_COMPARE_ATTEMPT_S:
        return min(base, available)
    # Tight: still try short compact if anything beyond report+buffer remains
    leave = REPORT_RESERVE_S + BUFFER_RESERVE_S
    tight = remaining - leave
    if tight <= 0:
        return 0.0
    return min(base, TIGHT_NODE_CAP_S, tight)


def effective_strategy_timeout_s(state: dict[str, Any], cfg: AnalysisModeConfig) -> float:
    """Strategy node budget: min(cfg, remaining - report/review reserve)."""
    base = float(getattr(cfg, "strategy_timeout_s", 0.0) or 0.0)
    if cfg.mode != "full":
        return base
    remaining = remaining_llm_budget_s(state, cfg)
    available = remaining - _downstream_reserve_for_strategy()
    if available < MIN_STRATEGY_ATTEMPT_S:
        if remaining <= 0:
            return 0.0
        return min(base, TIGHT_NODE_CAP_S, max(0.0, remaining - BUFFER_RESERVE_S))
    return min(base, available)


def split_primary_repair_timeouts(node_timeout_s: float) -> tuple[float, float]:
    """Primary LLM call ~78%; remainder for one short JSON repair."""
    node = max(0.0, float(node_timeout_s or 0.0))
    if node <= 0:
        return 0.0, 0.0
    primary = max(8.0, node * PRIMARY_LLM_FRACTION)
    if primary >= node:
        return node, 0.0
    repair = max(0.0, node - primary)
    if repair < 8.0:
        # Prefer giving almost all to primary when repair wouldn't be useful
        return node, 0.0
    return primary, repair


def budget_trace_metadata(state: dict[str, Any], cfg: AnalysisModeConfig) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "total_elapsed_s": round(elapsed_s(state), 2),
        "mode_total_budget_s": float(getattr(cfg, "mode_total_budget_s", 0.0) or 0.0),
    }
    if cfg.mode == "full":
        meta["remaining_llm_budget_s"] = round(remaining_llm_budget_s(state, cfg), 2)
    return meta
