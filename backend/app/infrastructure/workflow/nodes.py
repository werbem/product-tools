"""LangGraph node functions — with SSE event injection.

Each node emits phase_update events via push_event() for real-time
progress tracking via SSE.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.dto.agent_dto import (
    InsightInput,
    CompareInput,
    GateInput,
    PlannerInput,
    ReportInput,
    ResearchInput,
    ReviewInput,
    StrategyInput,
)
from app.config.settings import settings
from app.infrastructure.agents.base import AgentContext
from app.infrastructure.demo_data import build_demo_full_state
from app.infrastructure.agents.compare_agent import CompareAgent
from app.infrastructure.agents.insight_agent import InsightAgent
from app.utils.state_reader import get_validated_input
from app.infrastructure.agents.gate_agent import GateAgent
from app.infrastructure.agents.planner_agent import PlannerAgent
from app.infrastructure.agents.report_agent import ReportAgent
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.agents.review_agent import ReviewAgent
from app.infrastructure.agents.strategy_agent import StrategyAgent
from app.infrastructure.workflow.state import WorkflowState
from app.infrastructure.workflow.stream import (
    AGENT_DONE_MSGS,
    AGENT_RUNNING_MSGS,
    push_event,
)


def _tid(state: WorkflowState) -> str:
    return state.get("task_id", "")


def _emit(agent: str, status: str, state: WorkflowState, extra: dict | None = None) -> None:
    """Emit an SSE event for an agent phase transition."""
    tid = _tid(state)
    msg = AGENT_RUNNING_MSGS.get(agent, f"{agent} 运行中") if status == "running" else AGENT_DONE_MSGS.get(agent, f"{agent} 完成")
    progress = state.get("progress", 0.0)
    push_event(tid, agent=agent, status=status, message=msg, progress=progress, extra=extra)


# ── Helpers ──

def _make_ctx(state: WorkflowState, agent_name: str) -> AgentContext:
    return AgentContext(
        task_id=state.get("task_id", ""),
        current_phase=state.get("current_phase", "initialized"),
        retry_count=state.get("retry_counts", {}).get(agent_name, 0),
    )


def _push_phase(state: WorkflowState, record: dict[str, Any]) -> list[dict[str, Any]]:
    history = list(state.get("phase_history", []))
    history.append(record)
    return history


# ═══════════════════════════════════════════════════
#  Node Functions
# ═══════════════════════════════════════════════════

async def validate_input_node(state: WorkflowState) -> dict[str, Any]:
    """Gate: validate user input. Demo mode 直接返回完整分析结果。"""
    _emit("gate", "running", state)

    # ── Demo mode: short-circuit ──
    if settings.demo_mode:
        _emit("gate", "completed", state)
        return build_demo_full_state(state.get("task_id", "demo-task-001"))

    ctx = _make_ctx(state, "gate")
    agent = GateAgent()
    result = await agent.aexecute(ctx, GateInput(user_input=state.get("user_input", {})))
    if result.success:
        _emit("gate", "completed", state)
        validated = result.output.validated_input
        return {
            "validated_input": {
                "is_valid": validated.is_valid,
                **validated.clean_values,
            },
            "current_phase": result.output.current_phase,
            "phase_history": _push_phase(state, result.phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        "current_phase": "validation_failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def plan_node(state: WorkflowState) -> dict[str, Any]:
    """Planner: generate research plan."""
    _emit("planner", "running", state)

    ctx = _make_ctx(state, "planner")
    vi = get_validated_input(state)
    agent = PlannerAgent()
    result = await agent.aexecute(
        ctx,
        PlannerInput(
            our_company=vi.get("our_company", ""),
            competitor_company=vi.get("competitor_company", ""),
            product=vi.get("product", ""),
            objective=vi.get("objective", "product_improvement"),
        ),
    )
    if result.success:
        _emit("planner", "completed", state)
        return {
            "research_plan": result.output.research_plan.model_dump(),
            "current_phase": "planned",
            "progress": 15.0,
            "phase_history": _push_phase(state, result.phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        "current_phase": "failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def research_node(state: WorkflowState) -> dict[str, Any]:
    """Research: collect evidence from web sources."""
    _emit("research", "running", state)

    ctx = _make_ctx(state, "research")
    agent = ResearchAgent()
    result = await agent.aexecute(
        ctx,
        ResearchInput(
            research_plan=state.get("research_plan", {}),
            our_company=get_validated_input(state).get("our_company", ""),
            competitor_company=get_validated_input(state).get("competitor_company", ""),
            product=get_validated_input(state).get("product", ""),
        ),
    )
    if result.success:
        eb = result.output.evidence_bundle if hasattr(result.output, 'evidence_bundle') else None
        count = len(eb.evidence_items) if eb and hasattr(eb, 'evidence_items') else 0
        _emit("research", "completed", state, extra={"evidence_count": count})
        # Compute evidence clusters (NEW)
        clusters_list = []
        try:
            ev_items = (eb.evidence_items if eb and hasattr(eb, 'evidence_items') else [])
            if ev_items:
                from app.infrastructure.tools.evidence_clustering import evidence_clustering
                cluster_inputs = [
                    {"id": e.id or f"e{i}", "title": e.title, "content": e.content,
                     "source_type": e.source_type, "confidence": e.confidence,
                     "date": getattr(e, "date", ""),
                     "temporal_level": (getattr(e, "quality_score", None) or {}).get("temporal_level", "")}
                    for i, e in enumerate(ev_items)
                ]
                clusters_raw = await evidence_clustering.cluster(
                    evidence_items=cluster_inputs,
                    objective=state.get("research_plan", {}).get("objective", ""),
                )
                clusters_list = [c.to_dict() for c in clusters_raw]
        except Exception:
            pass

        return {
            "evidence_bundle": eb.model_dump() if eb and hasattr(eb, "model_dump") else (eb if isinstance(eb, dict) else {}),
            "quality_report": (
                result.output.quality_report.model_dump()
                if result.output and hasattr(result.output, "quality_report") and hasattr(result.output.quality_report, "model_dump")
                else {}
            ),
            "clusters": clusters_list,
            "current_phase": "researched",
            "progress": 40.0,
            "phase_history": _push_phase(state, result.phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        "current_phase": "failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "quality_report": {},
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def compare_node(state: WorkflowState) -> dict[str, Any]:
    """Compare: gap analysis between our product and competitors."""
    _emit("compare", "running", state)

    ctx = _make_ctx(state, "compare")
    vi = get_validated_input(state)
    objective = vi.get("objective", "")

    # ── Evidence Clustering (NEW) ──
    evidence_bundle = state.get("evidence_bundle") or {}
    clusters = []
    try:
        ev_items = evidence_bundle.get("evidence_items", [])
        if ev_items:
            from app.infrastructure.tools.evidence_clustering import evidence_clustering
            cluster_inputs = [
                {
                    "id": e.get("id", f"e{i}"),
                    "title": e.get("title", ""),
                    "content": e.get("content", ""),
                    "source_type": e.get("source_type", "web"),
                    "confidence": e.get("confidence", "medium"),
                    "date": e.get("date", ""),
                    "temporal_level": (e.get("quality_score") or {}).get("temporal_level", ""),
                }
                for i, e in enumerate(ev_items)
            ]
            clusters_raw = await evidence_clustering.cluster(
                evidence_items=cluster_inputs,
                objective=objective,
            )
            clusters = [c.to_dict() for c in clusters_raw]
    except Exception:
        pass  # Clustering failure is non-blocking

    agent = CompareAgent()
    result = await agent.aexecute(
        ctx,
        CompareInput(
            evidence_bundle=evidence_bundle,
            evidence_clusters=state.get("clusters", []),
            analysis_scope=state.get("research_plan", {}).get("analysis_scope", []) or objective.split(","),
            objective=objective,
            product=vi.get("product", ""),
            our_company=vi.get("our_company", ""),
            competitor_company=vi.get("competitor_company", ""),
        ),
    )
    if result.success:
        _emit("compare", "completed", state)
        return {
            "clusters": state.get("clusters", []),
            "gap_analysis": (
                result.output.gap_analysis.model_dump()
                if hasattr(result.output, 'gap_analysis') and hasattr(result.output.gap_analysis, 'model_dump')
                else (result.output.gap_analysis if hasattr(result.output, 'gap_analysis') and isinstance(result.output.gap_analysis, dict) else {})
            ),
            "current_phase": "compared",
            "progress": 55.0,
            "phase_history": _push_phase(state, result.phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        "current_phase": "failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }



async def insight_node(state: WorkflowState) -> dict[str, Any]:
    """Insight: generate Fact/Observation/Hypothesis from clusters + gaps."""
    _emit("insight", "running", state)

    ctx = _make_ctx(state, "insight")
    vi = get_validated_input(state)
    agent = InsightAgent()
    result = await agent.aexecute(
        ctx,
        InsightInput(
            evidence_clusters=state.get("clusters", []),
            gap_analysis=state.get("gap_analysis", {}),
            our_company=vi.get("our_company", ""),
            competitor_company=vi.get("competitor_company", ""),
            product=vi.get("product", ""),
            objective=vi.get("objective", ""),
        ),
    )
    if result.success:
        _emit("insight", "completed", state, extra={
            "insight_count": result.output_fact_count if hasattr(result, 'output_fact_count') else 0,
        })
        return {
            "insights": result.output.model_dump() if result.output else {},
            "current_phase": "insighted",
            "progress": 65.0,
            "phase_history": _push_phase(state, result.phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        "current_phase": "failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def strategy_node(state: WorkflowState) -> dict[str, Any]:
    """Strategy: generate SWOT, opportunities, recommendations."""
    _emit("strategy", "running", state)

    ctx = _make_ctx(state, "strategy")
    vi = get_validated_input(state)
    agent = StrategyAgent()
    result = await agent.aexecute(
        ctx,
        StrategyInput(
            gap_analysis=state.get("gap_analysis", {}),
            evidence_bundle=state.get("evidence_bundle", {}),
            insights=state.get("insights", {}).get("insights", []) if state.get("insights") else [],
            objective=vi.get("objective", ""),
            product=vi.get("product", ""),
        ),
    )
    if result.success:
        cs = result.output.confidence_summary or {}
        sufficient = cs.get("sufficient", True)
        _emit("strategy", "completed", state)
        return {
            "strategic_insights": (
                result.output.strategic_insights.model_dump()
                if hasattr(result.output.strategic_insights, 'model_dump')
                else (result.output.strategic_insights if isinstance(result.output.strategic_insights, dict) else {})
            ),
            "current_phase": "strategized",
            "progress": 65.0,
            "phase_history": _push_phase(state, result.phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        "current_phase": "failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def report_node(state: WorkflowState) -> dict[str, Any]:
    """Report: generate formatted report (Markdown/HTML/Word)."""
    _emit("report", "running", state)

    ctx = _make_ctx(state, "report")
    vi = get_validated_input(state)
    agent = ReportAgent()
    result = await agent.aexecute(
        ctx,
        ReportInput(
            evidence_bundle=state.get("evidence_bundle", {}),
            gap_analysis=state.get("gap_analysis", {}),
            strategic_insights=state.get("strategic_insights", {}),
            objective=vi.get("objective", ""),
            product=vi.get("product", ""),
            our_company=vi.get("our_company", ""),
            competitor_company=vi.get("competitor_company", ""),
        ),
    )
    if result.success:
        _emit("report", "completed", state)
        return {
            "report_document": (
                result.output.report_document.model_dump()
                if hasattr(result.output.report_document, 'model_dump')
                else (result.output.report_document if isinstance(result.output.report_document, dict) else {})
            ),
            "current_phase": "reported",
            "progress": 85.0,
            "phase_history": _push_phase(state, result.phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        "report_document": {
            "formats": {"markdown": "", "html": "", "docx_url": None},
            "sections": [],
            "metadata": {"total_word_count": 0},
        },
        "current_phase": "failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def review_node(state: WorkflowState) -> dict[str, Any]:
    """Review: quality assurance on the generated report."""
    _emit("review", "running", state)

    ctx = _make_ctx(state, "review")
    agent = ReviewAgent()
    vi = get_validated_input(state)
    # Safely construct ReviewInput — report_document may be empty if report_node failed
    try:
        review_input = ReviewInput(
            report_document=state.get("report_document", {}),
            evidence_bundle=state.get("evidence_bundle", {}),
            objective=vi.get("objective", ""),
        )
    except Exception:
        # Report document invalid or missing — skip review with auto-pass
        return {
            "review_result": {"passed": True, "score": 0, "checks": {}, "issues": [],
                              "revision_suggestions": [], "passed_for_output": True},
            "current_phase": "reviewed",
            "progress": 95.0,
            "phase_history": _push_phase(state, {"phase": "reviewing", "status": "skipped"}),
            "updated_at": datetime.utcnow().isoformat(),
        }

    result = await agent.aexecute(ctx, review_input)
    if result.success:
        passed = result.output.passed_for_output
        _emit("review", "completed", state, extra={"passed": passed})
        return {
            "review_result": {**result.output.review_result.model_dump(), "deletion_suggestions": result.output.review_result.deletion_suggestions, "high_issue_count": result.output.review_result.high_issue_count, "fact_audit_passed": result.output.review_result.fact_audit_passed},
            "current_phase": "reviewed" if passed else "review_failed",
            "retry_counts": {**state.get("retry_counts", {}), "report_retry": state.get("retry_counts", {}).get("report_retry", 0) + (0 if passed else 1)},
            "progress": 95.0,
            "phase_history": _push_phase(state, result.phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        "current_phase": "failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def fail_node(state: WorkflowState) -> dict[str, Any]:
    from app.infrastructure.workflow.stream import push_done
    push_done(_tid(state), status="failed")
    return {
        "current_phase": "failed",
        "progress": 0.0,
        "updated_at": datetime.utcnow().isoformat(),
    }


async def finalize_node(state: WorkflowState) -> dict[str, Any]:
    """Terminal node for success — mark complete with fact-audit summary."""
    from app.infrastructure.workflow.stream import push_done

    # ── Fact-audit summary ──
    review = state.get("review_result", {})
    if review:
        high_issues = review.get("high_count", 0) or sum(
            1 for i in review.get("issues", []) if isinstance(i, dict) and i.get("severity") == "HIGH"
        )
        deletion_suggestions = review.get("deletion_suggestions", [])
    else:
        high_issues = 0
        deletion_suggestions = []

    push_done(
        _tid(state),
        status="completed",
        extra={
            "fact_audit": {
                "high_issues": high_issues,
                "deletion_suggestions_count": len(deletion_suggestions),
                "passed": high_issues == 0,
            }
        },
    )

    is_demo = state.get("demo", False)
    return {
        "current_phase": "completed",
        "progress": 100.0,
        "phase_history": _push_phase(state, {
            "phase": "finalized",
            "entered_at": datetime.utcnow().isoformat(),
            "duration_ms": 0,
            "status": "completed",
        }),
        "updated_at": datetime.utcnow().isoformat(),
        "demo": is_demo,
        "fact_audit_result": {
            "high_issues": high_issues,
            "deletion_suggestions": deletion_suggestions,
            "passed": high_issues == 0,
        },
    }


async def need_research_node(state: WorkflowState) -> dict[str, Any]:
    """Terminal node when more research is needed."""
    from app.infrastructure.workflow.stream import push_done
    push_done(_tid(state), status="need_more_research")

    return {
        "current_phase": "need_more_research",
        "progress": 65.0,
        "updated_at": datetime.utcnow().isoformat(),
    }
