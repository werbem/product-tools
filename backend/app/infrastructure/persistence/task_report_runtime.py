"""Shared in-memory task/report runtime storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.infrastructure.persistence.file_store import load_reports, load_tasks, save_reports, save_tasks

_tasks: dict[str, dict[str, Any]] = load_tasks()
_reports: dict[str, dict[str, Any]] = load_reports()

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def get_tasks() -> dict[str, dict[str, Any]]:
    return _tasks


def get_reports() -> dict[str, dict[str, Any]]:
    return _reports


def persist_tasks() -> None:
    save_tasks(dict(_tasks))


def persist_reports() -> None:
    save_reports(dict(_reports))


def mark_task_terminal(
    task_id: str,
    *,
    status: str = "cancelled",
    error: str | None = None,
) -> dict[str, Any] | None:
    """Mark a task terminal in persistence (idempotent if already terminal)."""
    entry = _tasks.get(task_id)
    if not entry or not isinstance(entry, dict):
        return None

    current = str(entry.get("status") or "").lower().strip()
    if current in _TERMINAL_STATUSES:
        return entry

    terminal = status if status in _TERMINAL_STATUSES else "cancelled"
    now = datetime.utcnow().isoformat()
    entry["status"] = terminal
    if error:
        entry["error"] = error
    state = entry.get("state")
    if not isinstance(state, dict):
        state = {}
        entry["state"] = state
    state["updated_at"] = now
    if terminal in {"failed", "cancelled"}:
        state["current_phase"] = "failed"
        if error:
            state["error_info"] = error
        elif not state.get("error_info"):
            state["error_info"] = terminal
    persist_tasks()

    try:
        from app.infrastructure.workflow.stream import push_done

        push_done(task_id, status="failed" if terminal != "completed" else "completed")
    except Exception:
        pass

    return entry


def fail_orphaned_incomplete_tasks(*, reason: str = "server_restart") -> list[str]:
    """Fail incomplete long tasks left after process death (no in-process runner)."""
    failed: list[str] = []
    for task_id, entry in list(_tasks.items()):
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status") or "").lower().strip()
        if status in _TERMINAL_STATUSES:
            continue
        # Only touch entries that look like long workflows / have state.
        if not entry.get("state") and status not in {"", "pending", "running"}:
            continue
        mark_task_terminal(
            task_id,
            status="failed",
            error=reason,
        )
        failed.append(task_id)
    return failed


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
