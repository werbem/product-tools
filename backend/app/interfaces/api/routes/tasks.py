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
from app.application.dto.collection_dto import (
    CollectionDetailResponse,
    CollectionEvidenceItemDTO,
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
    from app.infrastructure.persistence import task_report_runtime

    task_str = str(task_id)
    report_tasks = task_report_runtime.get_tasks()
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

    # Prefer task entry status when workflow has finished.
    # current_phase often stays at "reviewed" (95%) even after completion.
    entry_status = str(entry.get("status") or "").lower()
    current_phase = state.get("current_phase", "unknown")
    progress_value = float(state.get("progress", 0.0) or 0.0)

    if entry_status == "completed":
        status = "completed"
        progress_value = 100.0
        current_agent = "completed"
    elif entry_status == "failed":
        status = "failed"
        current_agent = current_phase or "failed"
    elif current_phase == "collection_completed":
        status = "completed"
        progress_value = 100.0
        current_agent = "completed"
    else:
        status = current_phase
        current_agent = state.get("current_agent") or current_phase

    budget_meta = state.get("workflow_budget_meta") or {}
    total_elapsed = state.get("total_elapsed_s")
    if total_elapsed is None and isinstance(budget_meta, dict):
        total_elapsed = budget_meta.get("total_elapsed_s")

    return TaskProgressResponse(
        task_id=task_id,
        status=status,
        current_agent=current_agent,
        progress=progress_value,
        stage_hint=state.get("stage_hint"),
        total_elapsed_s=float(total_elapsed) if total_elapsed is not None else None,
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


@router.get("/{task_id}/collection", response_model=CollectionDetailResponse)
async def get_task_collection(task_id: UUID) -> CollectionDetailResponse:
    """Return intelligence collection digest for a task (no full report)."""
    from app.infrastructure.persistence import task_report_runtime

    task_str = str(task_id)
    entry = task_report_runtime.get_tasks().get(task_str, {})
    state = entry.get("state")
    if not state:
        raise HTTPException(status_code=404, detail="任务不存在")

    user_input = state.get("user_input") or {}
    validated = state.get("validated_input") or {}
    collection_doc = state.get("collection_document") or {}
    evidence_items = (state.get("evidence_bundle") or {}).get("evidence_items") or []
    meta = state.get("collection_meta") or {}
    quality = state.get("quality_report") or {}

    from app.application.services.collection_topic import (
        apply_topic_to_markdown,
        resolve_collection_topic_from_state,
    )

    topic_info = resolve_collection_topic_from_state(state)
    markdown = apply_topic_to_markdown(
        collection_doc.get("markdown"),
        topic_info["topic"],
    )

    entry_status = str(entry.get("status") or "pending").lower()
    error = entry.get("error")

    return CollectionDetailResponse(
        task_id=task_id,
        workflow_kind=str(entry.get("workflow_kind") or "intelligence_collection"),
        status=entry_status,
        our_company=validated.get("our_company") or user_input.get("our_company", ""),
        product=validated.get("product") or user_input.get("product", ""),
        objective=topic_info["topic"],
        topic=topic_info["topic"],
        topic_source=topic_info.get("topic_source") or "",
        objective_code=topic_info.get("objective_code") or "",
        markdown=markdown,
        evidence_items=[
            CollectionEvidenceItemDTO(
                id=str(item.get("id") or ""),
                title=str(item.get("title") or ""),
                source=str(item.get("source") or ""),
                source_type=str(item.get("source_type") or "web"),
                url=str(item.get("url") or ""),
                date=str(item.get("date") or ""),
                content=str(item.get("content") or ""),
                confidence=str(item.get("confidence") or "medium"),
                category=str(item.get("category") or ""),
            )
            for item in evidence_items
        ],
        evidence_count=len(evidence_items),
        sources_attempted=int(
            meta.get("sources_attempted", quality.get("sources_attempted", 0)) or 0,
        ),
        sources_succeeded=int(
            meta.get("sources_succeeded", quality.get("sources_succeeded", 0)) or 0,
        ),
        warnings=[str(w) for w in meta.get("warnings", [])],
        created_at=datetime.utcnow(),
        error=str(error) if error else None,
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
