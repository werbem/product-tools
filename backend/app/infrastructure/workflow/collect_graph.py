"""Standalone collection subgraph used by Competitive Intelligence MCP.

This graph reuses the existing GateAgent, PlannerAgent, ResearchAgent, and the
existing ``plan_node``/``research_node`` implementations. It does not include
compare, insight, strategy, report, or review.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from langgraph.graph import END, StateGraph

from app.application.dto.agent_dto import GateInput, UserInputDTO
from app.infrastructure.agents.base import AgentContext
from app.infrastructure.agents.gate_agent import GateAgent
from app.infrastructure.workflow.nodes import plan_node, research_node
from app.infrastructure.workflow.state import WorkflowState


def _push_phase(state: WorkflowState, record: dict[str, Any]) -> list[dict[str, Any]]:
    history = list(state.get("phase_history", []))
    history.append(record)
    return history


async def collect_validate_node(state: WorkflowState) -> dict[str, Any]:
    """Validate collection input without the demo-mode short circuit."""

    ctx = AgentContext(
        task_id=state.get("task_id", ""),
        current_phase="validating",
        retry_count=state.get("retry_counts", {}).get("gate", 0),
    )
    raw = state.get("user_input", {}) or {}
    optional = raw.get("optional") or {}
    if not isinstance(optional, dict):
        optional = {}
    # Align with deep analysis: pass scene so Gate can do effective_objective = scene or objective
    scene = (raw.get("scene") or "").strip() or None
    user_input = UserInputDTO(
        our_company=raw.get("our_company", ""),
        competitor_company=raw.get("competitor_company", ""),
        product=raw.get("product", ""),
        objective=raw.get("objective", "product_improvement"),
        scene=scene,
        optional=optional or None,
    )
    result = await GateAgent().aexecute(ctx, GateInput(user_input=user_input))

    if not result.success:
        return {
            "current_phase": "validation_failed",
            "errors": list(state.get("errors", [])) + [result.error or {}],
            "updated_at": datetime.utcnow().isoformat(),
        }

    validated = result.output.validated_input
    return {
        "validated_input": {
            "is_valid": validated.is_valid,
            **validated.clean_values,
        },
        "current_phase": result.output.current_phase,
        "phase_history": _push_phase(state, result.phase_record or {}),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def collect_plan_node(state: WorkflowState) -> dict[str, Any]:
    """Run the existing planner and apply optional dimension/source overrides."""

    plan_update = await plan_node(state)
    optional = (state.get("user_input") or {}).get("optional") or {}
    dimensions = optional.get("dimensions") or []
    source_types = optional.get("source_types") or []

    if dimensions or source_types:
        plan = dict(plan_update.get("research_plan") or {})
        if dimensions:
            plan["analysis_scope"] = list(dimensions)
        if source_types:
            plan["required_sources"] = list(source_types)
        plan_update["research_plan"] = plan

    return plan_update


async def prepare_collection_output(state: WorkflowState) -> dict[str, Any]:
    """Normalize collection metadata internally, without MCP-specific types."""

    evidence_items = (state.get("evidence_bundle") or {}).get("evidence_items", [])
    quality = state.get("quality_report") or {}

    warnings = [str(w) for w in quality.get("missing_data_warnings", [])]
    sources_attempted = int(quality.get("sources_attempted", 0) or 0)
    sources_succeeded = int(quality.get("sources_succeeded", 0) or 0)

    if not evidence_items:
        warnings.append("no evidence collected")
    elif sources_succeeded < sources_attempted:
        warnings.append(
            f"partial source success: {sources_succeeded}/{sources_attempted}"
        )

    return {
        "collection_meta": {
            "total_evidence": len(evidence_items),
            "sources_attempted": sources_attempted,
            "sources_succeeded": sources_succeeded,
            "warnings": warnings,
        },
        "current_phase": "collection_processed",
        "updated_at": datetime.utcnow().isoformat(),
    }


async def collection_output_node(state: WorkflowState) -> dict[str, Any]:
    """Mark the collection workflow as complete."""

    return {
        "current_phase": "collection_completed",
        "updated_at": datetime.utcnow().isoformat(),
    }


async def collect_fail_node(state: WorkflowState) -> dict[str, Any]:
    """Terminal node for invalid or failed collection."""

    return {
        "current_phase": "collection_failed",
        "updated_at": datetime.utcnow().isoformat(),
    }


def _route_after_collect_validate(state: WorkflowState) -> str:
    return "collect_plan_node" if state.get("current_phase") == "validated" else "collect_fail_node"


def _route_after_collect_plan(state: WorkflowState) -> str:
    return "research_node" if state.get("current_phase") != "failed" else "collect_fail_node"


def _route_after_research(state: WorkflowState) -> str:
    return "prepare_collection_output" if state.get("current_phase") != "failed" else "collect_fail_node"


def build_collect_graph() -> StateGraph:
    """Build and compile the collection-only LangGraph."""

    graph = StateGraph(WorkflowState)

    graph.add_node("collect_validate_node", collect_validate_node)
    graph.add_node("collect_plan_node", collect_plan_node)
    graph.add_node("research_node", research_node)
    graph.add_node("prepare_collection_output", prepare_collection_output)
    graph.add_node("collection_output_node", collection_output_node)
    graph.add_node("collect_fail_node", collect_fail_node)

    graph.set_entry_point("collect_validate_node")
    graph.add_conditional_edges(
        "collect_validate_node",
        _route_after_collect_validate,
        {
            "collect_plan_node": "collect_plan_node",
            "collect_fail_node": "collect_fail_node",
        },
    )
    graph.add_conditional_edges(
        "collect_plan_node",
        _route_after_collect_plan,
        {
            "research_node": "research_node",
            "collect_fail_node": "collect_fail_node",
        },
    )
    graph.add_conditional_edges(
        "research_node",
        _route_after_research,
        {
            "prepare_collection_output": "prepare_collection_output",
            "collect_fail_node": "collect_fail_node",
        },
    )
    graph.add_edge("prepare_collection_output", "collection_output_node")
    graph.add_edge("collection_output_node", END)
    graph.add_edge("collect_fail_node", END)

    return graph.compile()


collect_graph = build_collect_graph()
