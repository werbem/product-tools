"""LangGraph node functions — with SSE event injection.

Each node emits phase_update events via push_event() for real-time
progress tracking via SSE.
"""

from __future__ import annotations

import time
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


def _emit(
    agent: str,
    status: str,
    state: WorkflowState,
    extra: dict | None = None,
    *,
    stage_hint: str | None = None,
) -> None:
    """Emit an SSE event for an agent phase transition."""
    tid = _tid(state)
    msg = AGENT_RUNNING_MSGS.get(agent, f"{agent} 运行中") if status == "running" else AGENT_DONE_MSGS.get(agent, f"{agent} 完成")
    progress = state.get("progress", 0.0)
    hint = stage_hint or state.get("stage_hint")
    payload = {"phase": agent, "stage_hint": hint}
    if extra:
        payload.update(extra)
    push_event(tid, agent=agent, status=status, message=hint or msg, progress=progress, extra=payload)


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


def _memory_notes_for_strategy(state: WorkflowState) -> str | None:
    from app.application.services.context_blocks import (
        STRATEGY_MEMORY_LIMIT,
        STRATEGY_NOTES_LIMIT,
        build_memory_notes_context,
        optional_from_state,
    )

    return build_memory_notes_context(
        optional_from_state(state),
        memory_limit=STRATEGY_MEMORY_LIMIT,
        notes_limit=STRATEGY_NOTES_LIMIT,
    )


def _memory_notes_for_report(state: WorkflowState) -> str | None:
    from app.application.services.context_blocks import (
        REPORT_MEMORY_LIMIT,
        REPORT_NOTES_LIMIT,
        build_memory_notes_context,
        optional_from_state,
    )

    return build_memory_notes_context(
        optional_from_state(state),
        memory_limit=REPORT_MEMORY_LIMIT,
        notes_limit=REPORT_NOTES_LIMIT,
    )


def _budget_state_updates(state: WorkflowState, cfg) -> dict[str, Any]:
    """Track workflow monotonic start + elapsed for 720s watchdog."""
    from app.infrastructure.workflow.workflow_budget import (
        budget_trace_metadata,
        workflow_budget_patch,
    )

    patch = workflow_budget_patch(state)
    merged = {**state, **patch}
    meta = dict(state.get("workflow_budget_meta") or {})
    meta.update(budget_trace_metadata(merged, cfg))
    return {**patch, "workflow_budget_meta": meta}


async def _run_full_evidence_clustering(
    state: WorkflowState,
    cfg,
    evidence_bundle: Any,
    budget_updates: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Full-mode clustering with progress hints, timeout, and budget metadata."""
    import asyncio

    from app.infrastructure.persistence import task_report_runtime
    from app.infrastructure.workflow.progress_hints import RESEARCH_PROGRESS_HINTS

    clusters_list: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    eb = evidence_bundle
    ev_items = (eb.evidence_items if eb and hasattr(eb, "evidence_items") else [])
    if not ev_items:
        return clusters_list, meta

    merged = {**state, **budget_updates}
    task_report_runtime.touch_task_progress(
        _tid(state),
        current_phase="researching",
        progress=42.0,
        current_agent="research",
        stage_hint=RESEARCH_PROGRESS_HINTS[42.0],
    )
    _emit(
        "research",
        "clustering",
        {**merged, "progress": 42.0, "stage_hint": RESEARCH_PROGRESS_HINTS[42.0]},
        stage_hint=RESEARCH_PROGRESS_HINTS[42.0],
    )

    cluster_inputs = [
        {
            "id": e.id or f"e{i}",
            "title": e.title,
            "content": e.content,
            "source_type": e.source_type,
            "confidence": e.confidence,
            "date": getattr(e, "date", ""),
            "temporal_level": (getattr(e, "quality_score", None) or {}).get("temporal_level", ""),
        }
        for i, e in enumerate(ev_items)
    ]
    clustering_timeout = float(getattr(cfg, "clustering_timeout_s", 60.0) or 60.0)
    t0 = time.monotonic()
    try:
        from app.infrastructure.tools.evidence_clustering import evidence_clustering

        clusters_raw = await asyncio.wait_for(
            evidence_clustering.cluster(
                evidence_items=cluster_inputs,
                objective=state.get("research_plan", {}).get("objective", ""),
            ),
            timeout=clustering_timeout,
        )
        clusters_list = [c.to_dict() for c in clusters_raw]
        meta["clustering_elapsed_s"] = round(time.monotonic() - t0, 2)
    except asyncio.TimeoutError:
        meta["clustering_timeout"] = True
        meta["clustering_skipped"] = True
        meta["clustering_elapsed_s"] = round(time.monotonic() - t0, 2)
    except asyncio.CancelledError:
        raise
    except Exception:
        meta["clustering_skipped"] = True

    task_report_runtime.touch_task_progress(
        _tid(state),
        current_phase="researching",
        progress=44.0,
        current_agent="research",
        stage_hint=RESEARCH_PROGRESS_HINTS[44.0],
    )
    _emit(
        "research",
        "clustering_done",
        {**merged, "progress": 44.0, "stage_hint": RESEARCH_PROGRESS_HINTS[44.0]},
        stage_hint=RESEARCH_PROGRESS_HINTS[44.0],
    )
    return clusters_list, meta


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
    import asyncio

    from app.infrastructure.workflow.analysis_mode import (
        effective_plan_timeout_s,
        resolve_mode_config,
        trim_research_plan_for_mode,
    )
    from app.infrastructure.workflow.node_timeouts import log_node_timeout

    cfg = resolve_mode_config(state)
    plan_timeout = effective_plan_timeout_s(cfg, state)
    budget_updates = _budget_state_updates(state, cfg)
    _emit("planner", "running", state)

    ctx = _make_ctx(state, "planner")
    vi = get_validated_input(state)
    from app.application.services.context_blocks import (
        PLANNER_MEMORY_LIMIT,
        PLANNER_NOTES_LIMIT,
        build_memory_notes_context,
        optional_from_state,
    )

    optional_context = build_memory_notes_context(
        optional_from_state(state),
        memory_limit=PLANNER_MEMORY_LIMIT,
        notes_limit=PLANNER_NOTES_LIMIT,
    )
    planner_input = PlannerInput(
        our_company=vi.get("our_company", ""),
        competitor_company=vi.get("competitor_company", ""),
        product=vi.get("product", ""),
        objective=vi.get("objective", "product_improvement"),
        optional_context=optional_context,
        llm_timeout_seconds=plan_timeout,
    )
    agent = PlannerAgent()
    try:
        result = await asyncio.wait_for(
            agent.aexecute(ctx, planner_input),
            timeout=plan_timeout,
        )
    except asyncio.TimeoutError:
        log_node_timeout("plan", plan_timeout, mode=cfg.mode)
        mock_plan = PlannerAgent._mock_plan(planner_input)
        research_plan = trim_research_plan_for_mode(mock_plan.model_dump(), cfg)
        _emit("planner", "completed", state)
        return {
            **budget_updates,
            "research_plan": research_plan,
            "current_phase": "planned",
            "progress": 15.0,
            "phase_history": _push_phase(state, {
                "phase": "planned",
                "status": "completed",
                "error": f"plan_timeout_{int(plan_timeout)}s",
                "llm_generated": False,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }
    if result.success:
        _emit("planner", "completed", state)
        research_plan = trim_research_plan_for_mode(
            result.output.research_plan.model_dump(),
            cfg,
        )
        return {
            **budget_updates,
            "research_plan": research_plan,
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
    import asyncio

    from app.infrastructure.persistence import task_report_runtime
    from app.infrastructure.workflow.analysis_mode import effective_research_timeout_s, resolve_mode_config
    from app.infrastructure.workflow.node_timeouts import log_node_timeout
    from app.infrastructure.workflow.progress_hints import (
        RAW_TIMEOUT_FALLBACK_HINT,
        RESEARCH_PROGRESS_HINTS,
    )

    cfg = resolve_mode_config(state)
    research_timeout = effective_research_timeout_s(cfg, state)
    budget_updates = _budget_state_updates(state, cfg)
    optional = (state.get("user_input") or {}).get("optional") or {}
    skip_eval = cfg.skip_evidence_evaluation or bool(optional.get("skip_evidence_evaluation"))
    # Mid-node progress: otherwise UI stays at planned/15% for many minutes.
    task_report_runtime.touch_task_progress(
        _tid(state),
        current_phase="researching",
        progress=20.0,
        current_agent="research",
        stage_hint=RESEARCH_PROGRESS_HINTS[20.0],
    )
    _emit(
        "research",
        "running",
        {**state, **budget_updates, "progress": 20.0, "stage_hint": RESEARCH_PROGRESS_HINTS[20.0]},
        stage_hint=RESEARCH_PROGRESS_HINTS[20.0],
    )

    ctx = _make_ctx(state, "research")
    agent = ResearchAgent()
    research_input = ResearchInput(
        research_plan=state.get("research_plan", {}),
        our_company=get_validated_input(state).get("our_company", ""),
        competitor_company=get_validated_input(state).get("competitor_company", ""),
        product=get_validated_input(state).get("product", ""),
        time_budget_seconds=research_timeout,
        max_source_types=cfg.max_source_types,
        max_results_per_source=cfg.research_max_results,
        skip_evidence_evaluation=skip_eval,
        max_evidence_items=cfg.max_evidence_items if cfg.mode == "full" else None,
        max_evaluated_items=cfg.max_evaluated_items if cfg.mode == "full" else None,
        evidence_max_age_months=cfg.evidence_max_age_months,
        max_undated_evidence_items=cfg.max_undated_evidence_items,
        enable_lightweight_date_enrichment=cfg.enable_lightweight_date_enrichment,
        date_enrichment_timeout_s=cfg.date_enrichment_timeout_s,
        date_enrichment_max_urls=cfg.date_enrichment_max_urls,
    )
    timeout_phase_meta: dict[str, Any] = {}
    try:
        result = await asyncio.wait_for(
            agent.aexecute(ctx, research_input),
            timeout=research_timeout,
        )
    except asyncio.TimeoutError:
        log_node_timeout("research", research_timeout, mode=cfg.mode)
        partial = await agent.build_partial_result()
        if partial and partial.success:
            result = partial
            raw_pr = partial.phase_record or {}
            timeout_phase_meta = dict(raw_pr) if isinstance(raw_pr, dict) else {}
            used_raw_fallback = (
                timeout_phase_meta.get("evidence_fallback") == "raw_search"
                and bool(getattr(getattr(partial.output, "evidence_bundle", None), "evidence_items", None))
            )
            if used_raw_fallback:
                task_report_runtime.touch_task_progress(
                    _tid(state),
                    current_phase="researching",
                    progress=36.0,
                    current_agent="research",
                    stage_hint=RAW_TIMEOUT_FALLBACK_HINT,
                )
                _emit(
                    "research",
                    "running",
                    {**state, **budget_updates, "progress": 36.0, "stage_hint": RAW_TIMEOUT_FALLBACK_HINT},
                    stage_hint=RAW_TIMEOUT_FALLBACK_HINT,
                )
        else:
            return {
                **budget_updates,
                "evidence_bundle": state.get("evidence_bundle") or {},
                "quality_report": {
                    "sources_attempted": 0,
                    "sources_succeeded": 0,
                    "total_evidence_items": 0,
                    "research_timeout": True,
                    "missing_data_warnings": [f"Research 超时（{int(research_timeout)}s），已跳过剩余采集"],
                },
                "current_phase": "researched",
                "progress": 40.0,
                "phase_history": _push_phase(state, {
                    "phase": "researched",
                    "status": "completed",
                    "error": f"research_timeout_{int(research_timeout)}s",
                    "research_timeout": True,
                }),
                "updated_at": datetime.utcnow().isoformat(),
            }

    if result.success:
        eb = result.output.evidence_bundle if hasattr(result.output, 'evidence_bundle') else None
        count = len(eb.evidence_items) if eb and hasattr(eb, 'evidence_items') else 0
        _emit("research", "completed", state, extra={"evidence_count": count})
        # Compute evidence clusters (Full only; Fast/collection skip)
        clusters_list = []
        clustering_meta: dict[str, Any] = {}
        is_collection = (
            ((state.get("user_input") or {}).get("optional") or {}).get("workflow_kind")
            == "intelligence_collection"
        )
        skip_clustering = is_collection or cfg.skip_compare
        ev_items = (eb.evidence_items if eb and hasattr(eb, "evidence_items") else [])
        if ev_items and not skip_clustering:
            clusters_list, clustering_meta = await _run_full_evidence_clustering(
                state, cfg, eb, budget_updates,
            )
        elif not skip_clustering and not ev_items:
            from app.infrastructure.workflow.progress_hints import NO_EVIDENCE_CLUSTERING_HINT

            task_report_runtime.touch_task_progress(
                _tid(state),
                current_phase="researching",
                progress=42.0,
                current_agent="research",
                stage_hint=NO_EVIDENCE_CLUSTERING_HINT,
            )
            _emit(
                "research",
                "clustering_skipped",
                {**state, **budget_updates, "progress": 42.0, "stage_hint": NO_EVIDENCE_CLUSTERING_HINT},
                stage_hint=NO_EVIDENCE_CLUSTERING_HINT,
            )
            clustering_meta = {"clustering_skipped_no_evidence": True}

        phase_record = dict(result.phase_record or {})
        if cfg.skip_compare:
            phase_record["skipped_compare"] = True
        if timeout_phase_meta:
            phase_record.update({
                k: timeout_phase_meta[k]
                for k in (
                    "research_timeout",
                    "evidence_fallback",
                    "raw_items_converted",
                    "sources_succeeded",
                    "error",
                )
                if k in timeout_phase_meta
            })
            if not phase_record.get("error"):
                phase_record["error"] = f"research_timeout_{int(research_timeout)}s"

        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        wf_meta.update(clustering_meta)
        for key in (
            "research_timeout",
            "evidence_fallback",
            "raw_items_converted",
            "sources_succeeded",
        ):
            if key in timeout_phase_meta:
                wf_meta[key] = timeout_phase_meta[key]
        budget_out = {**budget_updates, "workflow_budget_meta": wf_meta}

        used_raw_fallback = (
            timeout_phase_meta.get("evidence_fallback") == "raw_search" and count > 0
        )
        if clustering_meta.get("clustering_skipped_no_evidence"):
            from app.infrastructure.workflow.progress_hints import NO_EVIDENCE_CLUSTERING_HINT

            stage_hint = NO_EVIDENCE_CLUSTERING_HINT
            progress_out = 42.0
        elif clusters_list or clustering_meta:
            stage_hint = RESEARCH_PROGRESS_HINTS[44.0]
            progress_out = 44.0
        elif used_raw_fallback:
            stage_hint = RAW_TIMEOUT_FALLBACK_HINT
            progress_out = 36.0
        else:
            stage_hint = RESEARCH_PROGRESS_HINTS[40.0]
            progress_out = 40.0

        return {
            **budget_out,
            "evidence_bundle": eb.model_dump() if eb and hasattr(eb, "model_dump") else (eb if isinstance(eb, dict) else {}),
            "quality_report": (
                result.output.quality_report.model_dump()
                if result.output and hasattr(result.output, "quality_report") and hasattr(result.output.quality_report, "model_dump")
                else {}
            ),
            "clusters": clusters_list,
            "current_phase": "researched",
            "progress": progress_out,
            "stage_hint": stage_hint,
            "phase_history": _push_phase(state, phase_record),
            "updated_at": datetime.utcnow().isoformat(),
        }
    return {
        **budget_updates,
        "current_phase": "failed",
        "errors": list(state.get("errors", [])) + [result.error],
        "quality_report": {},
        "phase_history": _push_phase(state, result.phase_record),
        "updated_at": datetime.utcnow().isoformat(),
    }


async def compare_node(state: WorkflowState) -> dict[str, Any]:
    """Compare: gap analysis between our product and competitors."""
    import asyncio

    from app.infrastructure.persistence import task_report_runtime
    from app.infrastructure.workflow.analysis_mode import resolve_mode_config
    from app.infrastructure.workflow.node_timeouts import log_node_timeout
    from app.infrastructure.workflow.progress_hints import (
        COMPARE_TIMEOUT_STUB_HINT,
        FULL_PHASE_ENTRY_HINTS,
    )
    from app.infrastructure.workflow.workflow_budget import (
        effective_compare_timeout_s,
        should_block_llm_for_budget,
        should_skip_compare_for_budget,
    )

    cfg = resolve_mode_config(state)
    budget_updates = _budget_state_updates(state, cfg)
    merged_state = {**state, **budget_updates}
    compare_entry = FULL_PHASE_ENTRY_HINTS["compare"]
    task_report_runtime.touch_task_progress(
        _tid(state),
        current_phase="comparing",
        progress=compare_entry[0],
        current_agent="compare",
        stage_hint=compare_entry[1],
    )
    _emit(
        "compare",
        "running",
        {**merged_state, "progress": compare_entry[0], "stage_hint": compare_entry[1]},
        stage_hint=compare_entry[1],
    )

    clusters = list(state.get("clusters") or [])

    if should_skip_compare_for_budget(merged_state, cfg) or should_block_llm_for_budget(merged_state, cfg):
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        wf_meta["compare_skipped_budget"] = True
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "clusters": clusters,
            "gap_analysis": state.get("gap_analysis") or {},
            "current_phase": "compared",
            "progress": 55.0,
            "phase_history": _push_phase(state, {
                "phase": "compared",
                "status": "completed",
                "compare_skipped_budget": True,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }

    ctx = _make_ctx(state, "compare")
    vi = get_validated_input(state)
    objective = vi.get("objective", "")
    evidence_bundle = state.get("evidence_bundle") or {}
    compare_timeout = effective_compare_timeout_s(merged_state, cfg)
    research_incomplete = bool(
        (state.get("workflow_budget_meta") or {}).get("research_timeout")
        or (state.get("quality_report") or {}).get("research_timeout")
    )
    use_compact = cfg.mode == "full"

    agent = CompareAgent()
    if compare_timeout <= 0:
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        wf_meta["compare_skipped_budget"] = True
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "clusters": clusters,
            "gap_analysis": state.get("gap_analysis") or {},
            "current_phase": "compared",
            "progress": 55.0,
            "phase_history": _push_phase(state, {
                "phase": "compared",
                "status": "completed",
                "compare_skipped_budget": True,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }

    compare_input = CompareInput(
        evidence_bundle=evidence_bundle,
        evidence_clusters=clusters,
        analysis_scope=state.get("research_plan", {}).get("analysis_scope", []) or objective.split(","),
        objective=objective,
        product=vi.get("product", ""),
        our_company=vi.get("our_company", ""),
        competitor_company=vi.get("competitor_company", ""),
        llm_timeout_seconds=compare_timeout,
        compact=use_compact,
        research_incomplete=research_incomplete,
    )
    try:
        result = await asyncio.wait_for(
            agent.aexecute(ctx, compare_input),
            timeout=compare_timeout,
        )
    except asyncio.TimeoutError:
        log_node_timeout("compare", compare_timeout, mode=cfg.mode)
        # Ensure input snapshot exists even if arun never started
        if getattr(agent, "_partial_input", None) is None:
            agent._partial_input = compare_input
        partial = agent.build_partial_result()
        phase_meta = dict(partial.phase_record or {})
        gap_dict = phase_meta.pop("gap_dict", None)
        if gap_dict is None and partial.output and getattr(partial.output, "gap_analysis", None):
            gap = partial.output.gap_analysis
            gap_dict = gap.model_dump() if hasattr(gap, "model_dump") else (gap if isinstance(gap, dict) else {})
        gap_dict = gap_dict or {}
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        for key in ("compare_timeout", "compare_fallback", "compare_partial", "stub_evidence_count"):
            if key in gap_dict:
                wf_meta[key] = gap_dict[key]
            elif key in phase_meta:
                wf_meta[key] = phase_meta[key]
        wf_meta["compare_mode"] = gap_dict.get("compare_fallback") or phase_meta.get("compare_fallback") or "evidence_stub"
        wf_meta["compare_timeout"] = True
        stage_hint = COMPARE_TIMEOUT_STUB_HINT
        task_report_runtime.touch_task_progress(
            _tid(state),
            current_phase="comparing",
            progress=50.0,
            current_agent="compare",
            stage_hint=stage_hint,
        )
        _emit(
            "compare",
            "completed",
            {**merged_state, "progress": 55.0, "stage_hint": stage_hint},
            stage_hint=stage_hint,
            extra={"compare_fallback": gap_dict.get("compare_fallback")},
        )
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "clusters": clusters,
            "gap_analysis": gap_dict,
            "current_phase": "compared",
            "progress": 55.0,
            "stage_hint": stage_hint,
            "phase_history": _push_phase(state, {
                "phase": "compared",
                "status": "completed",
                "error": f"compare_timeout_{int(compare_timeout)}s",
                "compare_timeout": True,
                "compare_fallback": gap_dict.get("compare_fallback"),
                "compare_partial": gap_dict.get("compare_partial"),
                "compare_mode": wf_meta.get("compare_mode"),
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }

    if result.success:
        phase_meta = dict(result.phase_record or {})
        gap_dump = (
            result.output.gap_analysis.model_dump()
            if hasattr(result.output, 'gap_analysis') and hasattr(result.output.gap_analysis, 'model_dump')
            else (result.output.gap_analysis if hasattr(result.output, 'gap_analysis') and isinstance(result.output.gap_analysis, dict) else {})
        )
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        if phase_meta.get("compare_mode"):
            wf_meta["compare_mode"] = phase_meta["compare_mode"]
        if phase_meta.get("compare_elapsed_s") is not None:
            wf_meta["compare_elapsed_s"] = phase_meta["compare_elapsed_s"]
        _emit("compare", "completed", state)
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "clusters": clusters,
            "gap_analysis": gap_dump,
            "current_phase": "compared",
            "progress": 55.0,
            "phase_history": _push_phase(state, phase_meta),
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
    import asyncio

    from app.infrastructure.persistence import task_report_runtime
    from app.infrastructure.workflow.analysis_mode import resolve_mode_config
    from app.infrastructure.workflow.node_timeouts import log_node_timeout
    from app.infrastructure.workflow.progress_hints import FULL_PHASE_ENTRY_HINTS
    from app.infrastructure.workflow.workflow_budget import (
        effective_node_timeout_s,
        should_block_llm_for_budget,
        should_skip_insight_for_budget,
    )

    cfg = resolve_mode_config(state)
    budget_updates = _budget_state_updates(state, cfg)
    merged_state = {**state, **budget_updates}
    insight_entry = FULL_PHASE_ENTRY_HINTS["insight"]
    task_report_runtime.touch_task_progress(
        _tid(state),
        current_phase="insighting",
        progress=insight_entry[0],
        current_agent="insight",
        stage_hint=insight_entry[1],
    )
    _emit(
        "insight",
        "running",
        {**merged_state, "progress": insight_entry[0], "stage_hint": insight_entry[1]},
        stage_hint=insight_entry[1],
    )

    if should_skip_insight_for_budget(merged_state, cfg) or should_block_llm_for_budget(merged_state, cfg):
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        wf_meta["insight_skipped_budget"] = True
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "insights": {},
            "current_phase": "insighted",
            "progress": 65.0,
            "phase_history": _push_phase(state, {
                "phase": "insighted",
                "status": "completed",
                "insight_skipped_budget": True,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }

    ctx = _make_ctx(state, "insight")
    vi = get_validated_input(state)
    agent = InsightAgent()
    insight_timeout = effective_node_timeout_s(merged_state, cfg, cfg.insight_timeout_s)
    if insight_timeout <= 0:
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        wf_meta["insight_skipped_budget"] = True
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "insights": {},
            "current_phase": "insighted",
            "progress": 65.0,
            "phase_history": _push_phase(state, {
                "phase": "insighted",
                "status": "completed",
                "insight_skipped_budget": True,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }
    try:
        result = await asyncio.wait_for(
            agent.aexecute(
                ctx,
                InsightInput(
                    evidence_clusters=state.get("clusters", []),
                    gap_analysis=state.get("gap_analysis", {}),
                    flat_evidence_items=(state.get("evidence_bundle") or {}).get("evidence_items") or [],
                    our_company=vi.get("our_company", ""),
                    competitor_company=vi.get("competitor_company", ""),
                    product=vi.get("product", ""),
                    objective=vi.get("objective", ""),
                    llm_timeout_seconds=insight_timeout,
                ),
            ),
            timeout=insight_timeout,
        )
    except asyncio.TimeoutError:
        log_node_timeout("insight", insight_timeout, mode=cfg.mode)
        return {
            **budget_updates,
            "insights": {},
            "current_phase": "insighted",
            "progress": 65.0,
            "phase_history": _push_phase(state, {
                "phase": "insighted",
                "status": "completed",
                "error": f"insight_timeout_{int(insight_timeout)}s",
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }
    if result.success:
        _emit("insight", "completed", state, extra={
            "insight_count": result.output_fact_count if hasattr(result, 'output_fact_count') else 0,
        })
        return {
            **budget_updates,
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
    import asyncio

    from app.infrastructure.persistence import task_report_runtime
    from app.infrastructure.workflow.analysis_mode import resolve_mode_config
    from app.infrastructure.workflow.node_timeouts import log_node_timeout
    from app.infrastructure.workflow.progress_hints import (
        FULL_PHASE_ENTRY_HINTS,
        STRATEGY_TIMEOUT_STUB_HINT,
    )
    from app.infrastructure.workflow.workflow_budget import (
        effective_strategy_timeout_s,
        should_block_llm_for_budget,
        should_skip_strategy_for_budget,
    )

    cfg = resolve_mode_config(state)
    budget_updates = _budget_state_updates(state, cfg)
    merged_state = {**state, **budget_updates}
    strategy_entry = FULL_PHASE_ENTRY_HINTS["strategy"]
    task_report_runtime.touch_task_progress(
        _tid(state),
        current_phase="strategizing",
        progress=strategy_entry[0],
        current_agent="strategy",
        stage_hint=strategy_entry[1],
    )
    _emit(
        "strategy",
        "running",
        {**merged_state, "progress": strategy_entry[0], "stage_hint": strategy_entry[1]},
        stage_hint=strategy_entry[1],
    )

    if should_skip_strategy_for_budget(merged_state, cfg) or should_block_llm_for_budget(merged_state, cfg):
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        wf_meta["strategy_skipped_budget"] = True
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "strategic_insights": {},
            "current_phase": "strategized",
            "progress": 72.0,
            "phase_history": _push_phase(state, {
                "phase": "strategized",
                "status": "completed",
                "strategy_skipped_budget": True,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }

    ctx = _make_ctx(state, "strategy")
    vi = get_validated_input(state)
    agent = StrategyAgent()
    strategy_timeout = effective_strategy_timeout_s(merged_state, cfg)
    research_incomplete = bool(
        (state.get("workflow_budget_meta") or {}).get("research_timeout")
        or (state.get("quality_report") or {}).get("research_timeout")
    )
    use_compact = cfg.mode == "full"
    if strategy_timeout <= 0:
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        wf_meta["strategy_skipped_budget"] = True
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "strategic_insights": {},
            "current_phase": "strategized",
            "progress": 72.0,
            "phase_history": _push_phase(state, {
                "phase": "strategized",
                "status": "completed",
                "strategy_skipped_budget": True,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }

    strategy_input = StrategyInput(
        gap_analysis=state.get("gap_analysis", {}),
        evidence_bundle=state.get("evidence_bundle", {}),
        insights=state.get("insights", {}).get("insights", []) if state.get("insights") else [],
        objective=vi.get("objective", ""),
        product=vi.get("product", ""),
        our_company=vi.get("our_company", ""),
        competitor_company=vi.get("competitor_company", ""),
        llm_timeout_seconds=strategy_timeout,
        compact=use_compact,
        research_incomplete=research_incomplete,
        memory_notes_context=_memory_notes_for_strategy(state),
    )
    try:
        result = await asyncio.wait_for(
            agent.aexecute(ctx, strategy_input),
            timeout=strategy_timeout,
        )
    except asyncio.TimeoutError:
        log_node_timeout("strategy", strategy_timeout, mode=cfg.mode)
        if getattr(agent, "_partial_input", None) is None:
            agent._partial_input = strategy_input
        partial = agent.build_partial_result()
        phase_meta = dict(partial.phase_record or {})
        si_dict = phase_meta.pop("strategy_dict", None)
        if si_dict is None and partial.output and getattr(partial.output, "strategic_insights", None):
            si = partial.output.strategic_insights
            si_dict = si.model_dump() if hasattr(si, "model_dump") else (si if isinstance(si, dict) else {})
        si_dict = si_dict or {}
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        for key in ("strategy_timeout", "strategy_fallback", "swot_source", "strategy_partial", "stub_evidence_count"):
            if key in si_dict:
                wf_meta[key] = si_dict[key]
            elif key in phase_meta:
                wf_meta[key] = phase_meta[key]
        wf_meta["strategy_mode"] = (
            si_dict.get("strategy_fallback")
            or phase_meta.get("strategy_fallback")
            or "evidence_stub"
        )
        wf_meta["strategy_timeout"] = True
        stage_hint = STRATEGY_TIMEOUT_STUB_HINT
        task_report_runtime.touch_task_progress(
            _tid(state),
            current_phase="strategizing",
            progress=68.0,
            current_agent="strategy",
            stage_hint=stage_hint,
        )
        _emit(
            "strategy",
            "completed",
            {**merged_state, "progress": 72.0, "stage_hint": stage_hint},
            stage_hint=stage_hint,
            extra={"strategy_fallback": si_dict.get("strategy_fallback")},
        )
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "strategic_insights": si_dict,
            "current_phase": "strategized",
            "progress": 72.0,
            "stage_hint": stage_hint,
            "phase_history": _push_phase(state, {
                "phase": "strategized",
                "status": "completed",
                "error": f"strategy_timeout_{int(strategy_timeout)}s",
                "strategy_timeout": True,
                "strategy_fallback": si_dict.get("strategy_fallback"),
                "strategy_mode": wf_meta.get("strategy_mode"),
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }
    if result.success:
        phase_meta = dict(result.phase_record or {})
        cs = result.output.confidence_summary or {}
        sufficient = cs.get("sufficient", True)
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        if phase_meta.get("strategy_mode"):
            wf_meta["strategy_mode"] = phase_meta["strategy_mode"]
        if phase_meta.get("strategy_elapsed_s") is not None:
            wf_meta["strategy_elapsed_s"] = phase_meta["strategy_elapsed_s"]
        _emit("strategy", "completed", state)
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "strategic_insights": (
                result.output.strategic_insights.model_dump()
                if hasattr(result.output.strategic_insights, 'model_dump')
                else (result.output.strategic_insights if isinstance(result.output.strategic_insights, dict) else {})
            ),
            "current_phase": "strategized",
            "progress": 72.0,
            "phase_history": _push_phase(state, phase_meta),
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
    import asyncio

    from app.infrastructure.persistence import task_report_runtime
    from app.infrastructure.workflow.analysis_mode import resolve_mode_config
    from app.infrastructure.workflow.node_timeouts import log_node_timeout
    from app.infrastructure.workflow.workflow_budget import (
        effective_node_timeout_s,
        should_block_llm_for_budget,
        should_use_compact_report,
    )
    from app.infrastructure.workflow.progress_hints import (
        FAST_REPORT_DONE_HINT,
        FAST_REPORT_SEGMENT_HINTS,
        FULL_PHASE_ENTRY_HINTS,
    )

    cfg = resolve_mode_config(state)
    budget_updates = _budget_state_updates(state, cfg)
    merged_state = {**state, **budget_updates}
    compact_report = should_use_compact_report(merged_state, cfg)
    if cfg.skip_compare:
        report_progress = 70.0
        report_hint = FAST_REPORT_SEGMENT_HINTS[1]
    else:
        report_entry = FULL_PHASE_ENTRY_HINTS["report"]
        report_progress = report_entry[0]
        report_hint = report_entry[1]
    task_report_runtime.touch_task_progress(
        _tid(state),
        current_phase="reporting",
        progress=report_progress,
        current_agent="report",
        stage_hint=report_hint,
    )
    _emit(
        "report",
        "running",
        {**merged_state, "progress": report_progress, "stage_hint": report_hint},
        stage_hint=report_hint,
    )

    ctx = _make_ctx(state, "report")
    vi = get_validated_input(state)
    report_timeout = effective_node_timeout_s(merged_state, cfg, cfg.report_timeout_s)
    report_input = ReportInput(
        evidence_bundle=state.get("evidence_bundle", {}),
        gap_analysis=state.get("gap_analysis", {}),
        strategic_insights=state.get("strategic_insights", {}),
        objective=vi.get("objective", ""),
        product=vi.get("product", ""),
        our_company=vi.get("our_company", ""),
        competitor_company=vi.get("competitor_company", ""),
        llm_timeout_seconds=report_timeout if report_timeout > 0 else cfg.report_timeout_s,
        segment_timeout_seconds=cfg.report_segment_timeout_s,
        fast_mode=cfg.skip_compare,
        compact_report=compact_report,
        memory_notes_context=_memory_notes_for_report(state),
    )
    agent = ReportAgent()

    if should_block_llm_for_budget(merged_state, cfg) or report_timeout <= 0:
        wf_meta = dict(budget_updates.get("workflow_budget_meta") or {})
        wf_meta["report_skipped_budget"] = True
        result = agent.build_timeout_fallback(report_input)
        _emit("report", "completed", state, stage_hint=FAST_REPORT_DONE_HINT)
        return {
            **budget_updates,
            "workflow_budget_meta": wf_meta,
            "report_document": (
                result.output.report_document.model_dump()
                if result.success and hasattr(result.output.report_document, "model_dump")
                else (result.output.report_document if result.success and isinstance(result.output.report_document, dict) else {})
            ),
            "current_phase": "reported",
            "progress": 85.0,
            "stage_hint": FAST_REPORT_DONE_HINT,
            "phase_history": _push_phase(state, {
                "phase": "reported",
                "status": "completed",
                "report_skipped_budget": True,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }

    try:
        result = await asyncio.wait_for(
            agent.aexecute(ctx, report_input),
            timeout=report_timeout,
        )
    except asyncio.TimeoutError:
        log_node_timeout("report", report_timeout, mode=cfg.mode)
        result = agent.build_timeout_fallback(report_input)
    if result.success:
        _emit("report", "completed", state, stage_hint=FAST_REPORT_DONE_HINT)
        return {
            **budget_updates,
            "report_document": (
                result.output.report_document.model_dump()
                if hasattr(result.output.report_document, 'model_dump')
                else (result.output.report_document if isinstance(result.output.report_document, dict) else {})
            ),
            "current_phase": "reported",
            "progress": 85.0,
            "stage_hint": FAST_REPORT_DONE_HINT,
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
    import asyncio

    from app.infrastructure.persistence import task_report_runtime
    from app.infrastructure.workflow.analysis_mode import resolve_mode_config
    from app.infrastructure.workflow.node_timeouts import log_node_timeout
    from app.infrastructure.workflow.workflow_budget import (
        effective_node_timeout_s,
        should_block_llm_for_budget,
        should_skip_review_for_budget,
    )
    from app.infrastructure.workflow.progress_hints import FULL_PHASE_ENTRY_HINTS

    cfg = resolve_mode_config(state)
    budget_updates = _budget_state_updates(state, cfg)
    merged_state = {**state, **budget_updates}

    if should_skip_review_for_budget(merged_state, cfg) or should_block_llm_for_budget(merged_state, cfg):
        agent = ReviewAgent()
        partial = agent.build_timeout_partial_review(budget_skipped=True)
        review_payload = partial.output.review_result.model_dump()
        review_payload["passed_for_output"] = True
        review_payload["timeout_partial"] = True
        review_payload["review_partial"] = True
        review_payload["review_skipped_total_budget"] = True
        return {
            **budget_updates,
            "review_result": review_payload,
            "current_phase": "reviewed",
            "progress": 95.0,
            "phase_history": _push_phase(state, partial.phase_record or {}),
            "updated_at": datetime.utcnow().isoformat(),
        }

    review_entry = FULL_PHASE_ENTRY_HINTS["review"]

    task_report_runtime.touch_task_progress(
        _tid(state),
        current_phase="reviewing",
        progress=review_entry[0],
        current_agent="review",
        stage_hint=review_entry[1],
    )
    _emit(
        "review",
        "running",
        {**merged_state, "progress": review_entry[0], "stage_hint": review_entry[1]},
        stage_hint=review_entry[1],
    )

    ctx = _make_ctx(state, "review")
    agent = ReviewAgent()
    vi = get_validated_input(state)
    review_timeout = effective_node_timeout_s(merged_state, cfg, cfg.review_timeout_s)
    # Safely construct ReviewInput — report_document may be empty if report_node failed
    try:
        review_input = ReviewInput(
            report_document=state.get("report_document", {}),
            evidence_bundle=state.get("evidence_bundle", {}),
            objective=vi.get("objective", ""),
            llm_timeout_seconds=review_timeout if review_timeout > 0 else cfg.review_timeout_s,
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

    try:
        result = await asyncio.wait_for(
            agent.aexecute(ctx, review_input),
            timeout=review_timeout,
        )
    except asyncio.TimeoutError:
        log_node_timeout("review", review_timeout, mode=cfg.mode)
        partial = agent.build_timeout_partial_review(budget_skipped=False)
        review_payload = partial.output.review_result.model_dump()
        review_payload["passed_for_output"] = True
        review_payload["timeout_partial"] = True
        review_payload["review_partial"] = True
        return {
            **budget_updates,
            "review_result": review_payload,
            "current_phase": "reviewed",
            "progress": 95.0,
            "phase_history": _push_phase(state, {
                "phase": "reviewing",
                "status": "completed",
                "error": f"review_timeout_{int(cfg.review_timeout_s)}s",
                "timeout_partial": True,
                "review_partial": True,
            }),
            "updated_at": datetime.utcnow().isoformat(),
        }

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
    from app.infrastructure.workflow.analysis_mode import resolve_mode_config
    from app.infrastructure.workflow.stream import push_done

    cfg = resolve_mode_config(state)
    budget_updates = _budget_state_updates(state, cfg)

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
        **budget_updates,
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
