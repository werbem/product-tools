"""Shared in-memory task/report runtime storage."""

from __future__ import annotations

from typing import Any

from app.infrastructure.persistence.file_store import load_reports, load_tasks, save_reports, save_tasks

_tasks: dict[str, dict[str, Any]] = load_tasks()
_reports: dict[str, dict[str, Any]] = load_reports()


def get_tasks() -> dict[str, dict[str, Any]]:
    return _tasks


def get_reports() -> dict[str, dict[str, Any]]:
    return _reports


def persist_tasks() -> None:
    save_tasks(dict(_tasks))


def persist_reports() -> None:
    save_reports(dict(_reports))


def touch_task_progress(
    task_id: str,
    *,
    current_phase: str,
    progress: float,
    current_agent: str | None = None,
    stage_hint: str | None = None,
    total_elapsed_s: float | None = None,
) -> None:
    """Update in-memory task progress mid-node so polling UI can move."""
    from app.infrastructure.workflow.progress_merge import merge_progress

    entry = _tasks.get(task_id)
    if not entry:
        return
    state = entry.get("state")
    if not isinstance(state, dict):
        state = {}
        entry["state"] = state

    merged_progress = merge_progress(state.get("progress"), progress)
    state["current_phase"] = current_phase
    state["progress"] = merged_progress
    if current_agent is not None:
        state["current_agent"] = current_agent
    if stage_hint:
        state["stage_hint"] = stage_hint
    if total_elapsed_s is not None:
        state["total_elapsed_s"] = float(total_elapsed_s)
        budget_meta = dict(state.get("workflow_budget_meta") or {})
        budget_meta["total_elapsed_s"] = float(total_elapsed_s)
        state["workflow_budget_meta"] = budget_meta

    from datetime import datetime

    state["updated_at"] = datetime.utcnow().isoformat()

    try:
        from app.infrastructure.workflow.stream import push_event

        push_event(
            task_id,
            agent=current_agent or current_phase,
            status="running",
            message=stage_hint or "",
            progress=merged_progress,
            extra={
                "phase": current_phase,
                "stage_hint": stage_hint,
                "total_elapsed_s": total_elapsed_s,
            },
        )
    except Exception:
        pass
