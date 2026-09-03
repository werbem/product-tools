"""Artifact entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.domain.entities.copilot_common import utc_now


ArtifactType = Literal["report", "evidence_package", "analysis_matrix", "recommendation"]


@dataclass
class Artifact:
    id: str
    type: ArtifactType
    title: str
    project_id: str
    task_id: str
    url: str
    conversation_id: str | None = None
    report_id: str | None = None
    version: int = 1
    created_at: datetime = field(default_factory=utc_now)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.title = self.title.strip()
        if not self.title:
            raise ValueError("title must not be empty")
        if self.version < 1:
            raise ValueError("version must be positive")


def stable_report_artifact_id(task_id: str) -> str:
    return f"artifact-report-{task_id}-v1"


def stable_evidence_artifact_id(task_id: str) -> str:
    return f"artifact-evidence-{task_id}-v1"
