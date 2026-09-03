"""Workflow event bus — lightweight per-task asyncio.Queue for SSE streaming.

Usage in nodes:
    from app.infrastructure.workflow.stream import push_event

    push_event(task_id, agent="planner", status="running",
               message="正在分析竞品数据...", progress=15)

Usage in SSE endpoint:
    from app.infrastructure.workflow.stream import subscribe, cleanup

    async for event in subscribe(task_id):
        yield f"event: phase_update\ndata: {json.dumps(event)}\n\n"
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, AsyncIterator, Optional


# ── In-memory event store ──
# task_id → asyncio.Queue[dict]
_event_queues: dict[str, asyncio.Queue[Optional[dict]]] = {}

# TTL for queues (seconds after last activity)
_QUEUE_TTL = 600  # 10 minutes
_queue_last_active: dict[str, float] = {}

# Agent display names for user-facing messages
AGENT_LABELS: dict[str, str] = {
    "gate": "输入校验",
    "planner": "制定研究计划",
    "research": "跨源证据采集",
    "insight": "情报洞察分析",
    "compare": "竞品差距分析",
    "strategy": "策略建议生成",
    "report": "报告排版生成",
    "review": "质量审查",
}

AGENT_RUNNING_MSGS: dict[str, str] = {
    "gate": "正在验证输入参数...",
    "planner": "正在制定研究计划...",
    "research": "正在搜索竞品资料...",
    "insight": "正在分析情报洞察...",
    "compare": "正在分析竞品差距...",
    "strategy": "正在生成产品策略...",
    "report": "正在生成分析报告...",
    "review": "正在审查报告质量...",
}

AGENT_DONE_MSGS: dict[str, str] = {
    "gate": "输入校验完成",
    "planner": "研究计划已生成",
    "research": "证据采集完成",
    "insight": "情报分析完成",
    "compare": "差距分析完成",
    "strategy": "策略建议已生成",
    "report": "报告已生成",
    "review": "审查完成",
}

# Progress mapping per agent phase
AGENT_PROGRESS: dict[str, float] = {
    "validated": 5.0,
    "planned": 15.0,
    "researched": 40.0,
    "compared": 55.0,
    "strategized": 65.0,
    "reported": 85.0,
    "reviewed": 95.0,
    "completed": 100.0,
}


def _get_queue(task_id: str) -> asyncio.Queue:
    """Get or create an event queue for a task."""
    if task_id not in _event_queues:
        _event_queues[task_id] = asyncio.Queue()
    _queue_last_active[task_id] = time.time()
    return _event_queues[task_id]


def push_event(
    task_id: str,
    agent: str,
    status: str,
    message: str = "",
    progress: float = 0.0,
    extra: Optional[dict] = None,
) -> None:
    """Push a workflow event to the task's event queue.

    Non-blocking: uses put_nowait. If no one is listening, the event is dropped.

    Args:
        task_id: Workflow task ID
        agent: Agent name (planner, research, compare, strategy, report, review)
        status: "running" or "completed"
        message: Human-readable status message
        progress: Progress percentage (0-100)
        extra: Optional extra data (e.g., evidence count)
    """
    if task_id not in _event_queues:
        return  # No listener — skip to avoid unbounded queue growth

    queue = _event_queues.get(task_id)
    if queue is None:
        return

    event = {
        "event_type": "phase_update",
        "agent": agent,
        "status": status,
        "message": message,
        "progress": progress,
        "timestamp": time.time(),
    }
    if extra:
        event["data"] = extra
        if extra.get("stage_hint"):
            event["stage_hint"] = extra["stage_hint"]

    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        pass  # Queue is bounded, drop if full


def push_done(task_id: str, status: str = "completed", extra: Optional[dict] = None) -> None:
    """Push a final 'done' event."""
    if task_id not in _event_queues:
        return
    queue = _event_queues.get(task_id)
    if queue is None:
        return
    event = {
        "event_type": "done",
        "status": status,
        "timestamp": time.time(),
    }
    if extra:
        event.update(extra)
    try:
        queue.put_nowait(event)
        # Signal completion
        queue.put_nowait(None)
    except asyncio.QueueFull:
        pass


async def subscribe(task_id: str, timeout: float = 300.0) -> AsyncIterator[dict]:
    """Subscribe to task events. Yields events as they arrive.

    Args:
        task_id: Workflow task ID
        timeout: Maximum seconds to wait (default 5 minutes)

    Yields:
        Event dicts with event_type, agent, status, message, progress, timestamp
    """
    queue = _get_queue(task_id)
    deadline = time.time() + timeout

    try:
        while time.time() < deadline:
            try:
                remaining = deadline - time.time()
                if remaining <= 0:
                    break
                event = await asyncio.wait_for(queue.get(), timeout=min(remaining, 30.0))
                if event is None:
                    # Done signal
                    break
                yield event
            except asyncio.TimeoutError:
                # Send heartbeat to keep connection alive
                yield {
                    "event_type": "heartbeat",
                    "timestamp": time.time(),
                }
                continue
    finally:
        pass  # Cleanup is handled separately


def cleanup(task_id: str) -> None:
    """Clean up a task's event queue."""
    queue = _event_queues.pop(task_id, None)
    if queue:
        # Drain remaining events
        while not queue.empty():
            try:
                queue.get_nowait()
            except asyncio.QueueEmpty:
                break
    _queue_last_active.pop(task_id, None)


def ensure_listener(task_id: str) -> None:
    """Ensure a queue exists for a task (call before starting workflow)."""
    _get_queue(task_id)
