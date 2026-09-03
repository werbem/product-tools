"""Workflow launch DTOs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorkflowLaunchContext:
    project_id: str | None = None
    conversation_id: str | None = None
    source_message_id: str | None = None


@dataclass
class WorkflowLaunchResult:
    task_id: str
    report_id: str
    status: str = "pending"
