"""Single-worker long-task busy gate helpers.

Assumes one uvicorn worker sharing the LLM client and EventBus.
Prefer a **global** incomplete deep/collection task scan; optional project_id
filter exists for tests / future multi-tenant hardening — global is safer
under the current single-worker deployment.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.infrastructure.persistence import task_report_runtime

_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_LONG_WORKFLOW_KINDS = frozenset({"deep_analysis", "intelligence_collection"})


@dataclass(frozen=True)
class BusyLongTask:
    task_id: str
    workflow_kind: str  # deep_analysis | intelligence_collection
    project_id: str | None
    status: str


def _entry_workflow_kind(entry: dict[str, Any]) -> str:
    kind = entry.get("workflow_kind")
    if isinstance(kind, str) and kind.strip():
        return kind.strip()
    state = entry.get("state") if isinstance(entry.get("state"), dict) else {}
    optional = {}
    user_input = state.get("user_input") if isinstance(state, dict) else None
    if isinstance(user_input, dict):
        opt = user_input.get("optional")
        if isinstance(opt, dict):
            optional = opt
    wk = optional.get("workflow_kind")
    if isinstance(wk, str) and wk.strip():
        return wk.strip()
    # Deep launcher historically omitted workflow_kind on the entry.
    return "deep_analysis"


def _is_incomplete_long_task(entry: dict[str, Any]) -> bool:
    status = str(entry.get("status") or "").lower().strip()
    if status in _TERMINAL_STATUSES:
        return False
    kind = _entry_workflow_kind(entry)
    if kind not in _LONG_WORKFLOW_KINDS:
        # Unknown / legacy entries without kind still count as long if pending.
        # Treat empty/pending/running as busy long-task for single-worker safety.
        return status in {"", "pending", "running"} or bool(entry.get("state"))
    return True


def find_busy_long_task(
    *,
    project_id: str | None = None,
    tasks: dict[str, dict[str, Any]] | None = None,
) -> BusyLongTask | None:
    """Return the first incomplete Deep/Collection task, if any.

    Default scope is **global** (any project). Pass project_id to narrow;
    production conversation gate should keep project_id=None for single-worker.
    """
    store = tasks if tasks is not None else task_report_runtime.get_tasks()
    for task_id, entry in store.items():
        if not isinstance(entry, dict):
            continue
        if project_id is not None and str(entry.get("project_id") or "") != str(project_id):
            continue
        if not _is_incomplete_long_task(entry):
            continue
        return BusyLongTask(
            task_id=str(entry.get("task_id") or task_id),
            workflow_kind=_entry_workflow_kind(entry),
            project_id=str(entry["project_id"]) if entry.get("project_id") else None,
            status=str(entry.get("status") or "pending"),
        )
    return None


def launcher_has_in_process(
    deep_launcher: Any | None = None,
    collection_launcher: Any | None = None,
) -> bool:
    """OR in-process asyncio background sets (same worker only)."""
    for launcher in (deep_launcher, collection_launcher):
        if launcher is None:
            continue
        running = getattr(launcher, "_running", None)
        if running:
            return True
        # Optional public helper if present
        probe = getattr(launcher, "has_in_process_tasks", None)
        if callable(probe) and probe():
            return True
    return False


def resolve_busy(
    *,
    deep_launcher: Any | None = None,
    collection_launcher: Any | None = None,
    project_id: str | None = None,
    tasks: dict[str, dict[str, Any]] | None = None,
) -> BusyLongTask | None:
    """Persistence incomplete ∪ in-process launcher tasks.

    Global persistence scan first; if only in-process is set, synthesize a
    placeholder BusyLongTask without a stable id.
    """
    # Global scan — do not pass project_id for single-worker gate.
    found = find_busy_long_task(project_id=None, tasks=tasks)
    if found:
        return found
    if launcher_has_in_process(deep_launcher, collection_launcher):
        return BusyLongTask(
            task_id="in-process",
            workflow_kind="deep_analysis",
            project_id=project_id,
            status="running",
        )
    return None


def busy_user_message(busy: BusyLongTask) -> str:
    label = "信息收集" if busy.workflow_kind == "intelligence_collection" else "分析"
    tid = busy.task_id
    return (
        f"当前已有{label}任务进行中（task_id={tid}），请待完成后重试；"
        "可先追问已有结论，或发送信息查询 / 简答类问题。"
    )
