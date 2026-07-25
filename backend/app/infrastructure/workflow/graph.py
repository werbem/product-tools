"""LangGraph graph definition.

Compiles all nodes into a StateGraph with conditional edges.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

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


def _route_from_strategy(state: WorkflowState) -> str:
    """After strategy: always go to report (even with limited evidence).

    Previously, insufficient evidence routed to need_research_node (dead end).
    Now we always generate a report — lower quality is better than no report.
    The report agent will note when evidence is limited.
    """
    return "report_node"


def _route_from_review(state: WorkflowState) -> str:
    """After review: always finalize (review is advisory, not a gate).

    Review issues are recorded in the state for display in the final report.
    The report is always delivered regardless of review score.
    """
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

    # ── Main pipeline (sequential) ──
    graph.add_edge("plan_node", "research_node")
    graph.add_edge("research_node", "compare_node")
    graph.add_edge("compare_node", "insight_node")
    graph.add_edge("insight_node", "strategy_node")

    # ── Strategy → always report (evidence limitation noted in report) ──
    graph.add_edge("strategy_node", "report_node")
    graph.add_edge("report_node", "review_node")

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

    # ── Terminals ──
    graph.add_edge("finalize_node", END)
    graph.add_edge("fail_node", END)
    graph.add_edge("need_research_node", END)

    return graph.compile()


# Compiled singleton
workflow_graph = build_workflow_graph()
