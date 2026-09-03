"""Project application service."""

from __future__ import annotations

from typing import Any

from app.application.exceptions import ProjectNotFoundError
from app.domain.entities.analysis_project import AnalysisProject
from app.domain.entities.copilot_common import utc_now
from app.infrastructure.persistence import task_report_runtime
from app.infrastructure.persistence.copilot.exceptions import NotFoundError
from app.infrastructure.persistence.copilot.stores import (
    ArtifactStore,
    ConversationStore,
    MessageStore,
    ProjectStore,
    new_id,
)


class ProjectService:
    def __init__(
        self,
        store: ProjectStore,
        conversation_store: ConversationStore | None = None,
        message_store: MessageStore | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._store = store
        self._conversation_store = conversation_store
        self._message_store = message_store
        self._artifact_store = artifact_store

    def create_project(
        self,
        title: str,
        objective: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AnalysisProject:
        now = utc_now()
        project = AnalysisProject(
            id=new_id(),
            title=title,
            objective=objective,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        return self._store.create_project(project)

    def get_project(self, project_id: str) -> AnalysisProject:
        project = self._store.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(project_id)
        return project

    def list_projects(self) -> list[AnalysisProject]:
        return self._store.list_projects()

    def archive_project(self, project_id: str) -> AnalysisProject:
        project = self.get_project(project_id)
        project.status = "archived"
        project.updated_at = utc_now()
        return self._store.update_project(project)

    def touch_project(self, project_id: str) -> AnalysisProject:
        project = self.get_project(project_id)
        project.updated_at = utc_now()
        return self._store.update_project(project)

    def delete_project(self, project_id: str) -> dict[str, Any]:
        """Delete project and cascade conversations/messages/artifacts/reports/tasks."""
        self.get_project(project_id)

        conversation_ids: list[str] = []
        task_ids: set[str] = set()

        if self._conversation_store:
            conversation_ids = self._conversation_store.delete_conversations_by_project(project_id)

        if self._message_store and conversation_ids:
            for tid in self._message_store.delete_messages_by_conversation_ids(conversation_ids):
                task_ids.add(tid)

        if self._artifact_store:
            for tid in self._artifact_store.delete_artifacts_by_project(project_id):
                task_ids.add(tid)

        # Also collect task ids from task runtime linked to this project
        tasks = task_report_runtime.get_tasks()
        reports = task_report_runtime.get_reports()
        for tid, entry in list(tasks.items()):
            if entry.get("project_id") == project_id or tid in task_ids:
                task_ids.add(tid)

        for tid in task_ids:
            tasks.pop(tid, None)
            reports.pop(tid, None)

        try:
            self._store.delete_project(project_id)
        except NotFoundError as exc:
            raise ProjectNotFoundError(project_id) from exc

        task_report_runtime.persist_tasks()
        task_report_runtime.persist_reports()

        return {
            "project_id": project_id,
            "deleted_conversations": len(conversation_ids),
            "deleted_tasks": len(task_ids),
        }
