"""LangGraph graph definition.

Compiles all nodes into a StateGraph with conditional edges.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from app.infrastructure.workflow.analysis_mode import resolve_mode_config
from app.infrastructure.workflow.nodes import (
    compare_node,
    insight_node,
    fail_node,
    finalize_node,
    need_research_node,
    plan_node,
    report_node,
    research_node,
    review_node,
    strategy_node,
    validate_input_node,
)
from app.infrastructure.workflow.state import WorkflowState


def _route_from_validate(state: WorkflowState) -> str:
    """After validate: valid → plan, demo → finalize, invalid → fail."""
    if state.get("demo"):
        return "finalize_node"
    cp = state.get("current_phase", "")
    return "plan_node" if cp == "validated" else "fail_node"


def _route_after_research(state: WorkflowState) -> str:
    """Fast mode skips Compare and routes directly to Report."""
    cfg = resolve_mode_config(state)
    if cfg.skip_compare:
        return "report_node"
    return "compare_node"


def _route_after_compare(state: WorkflowState) -> str:
    """Fast mode skips insight/strategy and goes straight to report."""
    cfg = resolve_mode_config(state)
    if cfg.skip_insight and cfg.skip_strategy:
        return "report_node"
    if cfg.skip_insight:
        return "strategy_node"
    return "insight_node"


def _route_after_insight(state: WorkflowState) -> str:
    cfg = resolve_mode_config(state)
    if cfg.skip_strategy:
        return "report_node"
    return "strategy_node"


def _route_after_report(state: WorkflowState) -> str:
    cfg = resolve_mode_config(state)
    if cfg.skip_review:
        return "finalize_node"
    return "review_node"


def _route_from_review(state: WorkflowState) -> str:
    """After review: always finalize (review is advisory, not a gate)."""
    return "finalize_node"


def build_workflow_graph() -> StateGraph:
    """Build and compile the LangGraph StateGraph."""

    graph = StateGraph(WorkflowState)

    # ── Register nodes ──
    graph.add_node("validate_input_node", validate_input_node)
    graph.add_node("plan_node", plan_node)
    graph.add_node("research_node", research_node)
    graph.add_node("compare_node", compare_node)
    graph.add_node("insight_node", insight_node)
    graph.add_node("strategy_node", strategy_node)
    graph.add_node("need_research_node", need_research_node)
    graph.add_node("report_node", report_node)
    graph.add_node("review_node", review_node)
    graph.add_node("finalize_node", finalize_node)
    graph.add_node("fail_node", fail_node)

    # ── Set entry ──
    graph.set_entry_point("validate_input_node")

    # ── Conditional: validate → plan | fail | finalize (demo) ──
    graph.add_conditional_edges(
        "validate_input_node",
        _route_from_validate,
        {"plan_node": "plan_node", "fail_node": "fail_node", "finalize_node": "finalize_node"},
    )

    # ── Main pipeline ──
    graph.add_edge("plan_node", "research_node")
    graph.add_conditional_edges(
        "research_node",
        _route_after_research,
        {
            "compare_node": "compare_node",
            "report_node": "report_node",
        },
    )
    graph.add_conditional_edges(
        "compare_node",
        _route_after_compare,
        {
            "insight_node": "insight_node",
            "strategy_node": "strategy_node",
            "report_node": "report_node",
        },
    )
    graph.add_conditional_edges(
        "insight_node",
        _route_after_insight,
        {
            "strategy_node": "strategy_node",
            "report_node": "report_node",
        },
    )
    graph.add_edge("strategy_node", "report_node")
    graph.add_conditional_edges(
        "report_node",
        _route_after_report,
        {
            "review_node": "review_node",
            "finalize_node": "finalize_node",
        },
    )

    # ── Review → always finalize ──
    graph.add_conditional_edges(
        "review_node",
        _route_from_review,
        {
            "finalize_node": "finalize_node",
            "report_node": "report_node",
            "fail_node": "fail_node",
        },
    )

    graph.add_edge("finalize_node", END)
    graph.add_edge("fail_node", END)
    graph.add_edge("need_research_node", END)

    return graph.compile()


# Module-level compiled graph used by launcher / API.
workflow_graph = build_workflow_graph()
