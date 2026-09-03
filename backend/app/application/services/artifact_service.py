"""Artifact application service."""

from __future__ import annotations

from app.application.exceptions import ArtifactNotFoundError
from app.domain.entities.artifact import (
    Artifact,
    stable_evidence_artifact_id,
    stable_report_artifact_id,
)
from app.infrastructure.persistence.copilot.stores import ArtifactStore


class ArtifactService:
    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def create_report_artifact(
        self,
        *,
        project_id: str,
        conversation_id: str | None,
        task_id: str,
        report_id: str,
        title: str,
    ) -> Artifact:
        artifact = Artifact(
            id=stable_report_artifact_id(task_id),
            type="report",
            title=title,
            project_id=project_id,
            conversation_id=conversation_id,
            task_id=task_id,
            report_id=report_id,
            url=f"/api/reports/{report_id}",
            metadata={"download_url": f"/api/reports/{report_id}/download"},
        )
        return self._store.get_or_create_report_artifact_v1(artifact)

    def create_evidence_artifact(
        self,
        *,
        project_id: str,
        conversation_id: str | None,
        task_id: str,
        title: str,
    ) -> Artifact:
        artifact = Artifact(
            id=stable_evidence_artifact_id(task_id),
            type="evidence_package",
            title=title,
            project_id=project_id,
            conversation_id=conversation_id,
            task_id=task_id,
            report_id=None,
            url=f"/api/tasks/{task_id}/collection",
            metadata={"view_url": f"/workspace/collections/{task_id}"},
        )
        return self._store.get_or_create_evidence_artifact_v1(artifact)

    def get_artifact(self, artifact_id: str) -> Artifact:
        artifact = self._store.get_artifact(artifact_id)
        if not artifact:
            raise ArtifactNotFoundError(artifact_id)
        return artifact

    def list_artifacts(
        self,
        *,
        project_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
    ) -> list[Artifact]:
        return self._store.list_artifacts(
            project_id=project_id,
            conversation_id=conversation_id,
            task_id=task_id,
        )
