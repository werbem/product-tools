"""Tasks API — progress tracking & real-time SSE streaming."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.application.dto.task_dto import (
    PhaseRecordDTO,
    TaskDecisionRequest,
    TaskProgressResponse,
)
from app.infrastructure.workflow.stream import subscribe, cleanup

router = APIRouter(prefix="/tasks", tags=["tasks"])

# ── In-memory store (Phase 1 mock) ──
_tasks: dict[str, dict] = {}


def _register_task(task_id: str) -> None:
    if task_id not in _tasks:
        _tasks[task_id] = {
            "task_id": task_id,
            "status": "pending",
            "current_agent": "",
            "progress": 0.0,
            "phase_history": [],
            "error_info": None,
            "diagnosis": None,
            "created_at": datetime.utcnow(),
            "started_at": None,
            "completed_at": None,
        }


@router.get("/{task_id}/progress", response_model=TaskProgressResponse)
async def get_task_progress(task_id: UUID) -> TaskProgressResponse:
    """Get the current progress of an analysis task (polling)."""
    from app.interfaces.api.routes.reports import _tasks as report_tasks

    task_str = str(task_id)
    entry = report_tasks.get(task_str, {})
    state = entry.get("state")

    if not state:
        raise HTTPException(status_code=404, detail="任务不存在")

    history = state.get("phase_history", [])
    # Collect error info from entry, state["error_info"], or state["errors"]
    _raw_error = (
        entry.get("error")
        or state.get("error_info")
        or (state.get("errors", [None])[-1] if state.get("errors") else None)
    )
    error_info = str(_raw_error) if _raw_error and not isinstance(_raw_error, str) else _raw_error

    # Expose diagnosis if available (from workflow exception handler)
    diagnosis = entry.get("diagnosis") or None

    return TaskProgressResponse(
        task_id=task_id,
        status=state.get("current_phase", "unknown"),
        current_agent=state.get("current_phase", ""),
        progress=state.get("progress", 0.0),
        error_info=error_info,
        diagnosis=diagnosis,
        phase_history=[
            PhaseRecordDTO(
                phase=h.get("phase", ""),
                entered_at=h.get("entered_at", datetime.utcnow().isoformat()),
                duration_ms=h.get("duration_ms", 0),
                status=h.get("status", "running"),
                error=h.get("error"),
            )
            for h in (history or [])
        ],
        created_at=datetime.utcnow(),
    )


@router.get("/{task_id}/stream")
async def stream_task_progress(task_id: UUID):
    """SSE endpoint — streams workflow events in real time.

    Returns Server-Sent Events with:
      event: phase_update  — agent status changes
      event: done          — workflow complete
      event: heartbeat     — keep-alive (every 30s)

    Client: new EventSource("/api/tasks/{task_id}/stream")
    """
    task_str = str(task_id)

    async def event_generator():
        try:
            async for event in subscribe(task_str, timeout=600.0):
                event_type = event.get("event_type", "heartbeat")
                yield f"event: {event_type}\n"
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        finally:
            cleanup(task_str)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.patch("/{task_id}/decision")
async def submit_human_decision(
    task_id: UUID,
    body: TaskDecisionRequest,
) -> dict:
    """Submit a human decision for a HITL checkpoint (Phase 2)."""
    _ = task_id, body
    raise HTTPException(status_code=501, detail="Human-in-the-Loop 将在 Phase 2 实现")
