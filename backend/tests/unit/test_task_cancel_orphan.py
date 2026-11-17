"""Cancel / orphan reclaim for long-running tasks."""

from __future__ import annotations

from app.infrastructure.persistence import task_report_runtime
from app.application.services.workflow_busy import find_busy_long_task


def test_mark_task_terminal_frees_busy_gate(monkeypatch):
    tasks = {
        "t1": {
            "task_id": "t1",
            "status": "pending",
            "workflow_kind": "deep_analysis",
            "project_id": "p1",
            "state": {"current_phase": "initialized", "progress": 0.0},
        },
    }
    monkeypatch.setattr(task_report_runtime, "_tasks", tasks)
    monkeypatch.setattr(task_report_runtime, "persist_tasks", lambda: None)

    assert find_busy_long_task(tasks=tasks) is not None
    updated = task_report_runtime.mark_task_terminal(
        "t1",
        status="cancelled",
        error="cancelled_by_user",
    )
    assert updated is not None
    assert updated["status"] == "cancelled"
    assert find_busy_long_task(tasks=tasks) is None


def test_fail_orphaned_incomplete_tasks(monkeypatch):
    tasks = {
        "alive": {
            "task_id": "alive",
            "status": "pending",
            "workflow_kind": "deep_analysis",
            "state": {"current_phase": "initialized"},
        },
        "done": {
            "task_id": "done",
            "status": "completed",
            "workflow_kind": "deep_analysis",
            "state": {"current_phase": "reviewed"},
        },
    }
    monkeypatch.setattr(task_report_runtime, "_tasks", tasks)
    monkeypatch.setattr(task_report_runtime, "persist_tasks", lambda: None)

    failed = task_report_runtime.fail_orphaned_incomplete_tasks(reason="server_restart")
    assert failed == ["alive"]
    assert tasks["alive"]["status"] == "failed"
    assert tasks["done"]["status"] == "completed"
    assert find_busy_long_task(tasks=tasks) is None
