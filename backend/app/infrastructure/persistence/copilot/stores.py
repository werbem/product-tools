"""Copilot JSON stores for projects, conversations, messages, artifacts."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.config.settings import settings
from app.domain.entities.analysis_project import AnalysisProject
from app.domain.entities.artifact import (
    Artifact,
    stable_evidence_artifact_id,
    stable_report_artifact_id,
)
from app.domain.entities.conversation import Conversation
from app.domain.entities.copilot_common import from_iso, utc_now
from app.domain.entities.message import Message
from app.infrastructure.persistence.copilot.exceptions import DuplicateIdError, NotFoundError
from app.infrastructure.persistence.copilot.json_file_store import JsonFileStore

DATA_DIR = settings.data_dir / "persistence"


def _project_from_dict(data: dict[str, Any]) -> AnalysisProject:
    return AnalysisProject(
        id=data["id"],
        title=data["title"],
        objective=data.get("objective"),
        status=data.get("status", "active"),
        created_at=from_iso(data["created_at"]),
        updated_at=from_iso(data["updated_at"]),
        metadata=dict(data.get("metadata") or {}),
    )


def _conversation_from_dict(data: dict[str, Any]) -> Conversation:
    return Conversation(
        id=data["id"],
        project_id=data["project_id"],
        title=data.get("title"),
        status=data.get("status", "active"),
        created_at=from_iso(data["created_at"]),
        updated_at=from_iso(data["updated_at"]),
        metadata=dict(data.get("metadata") or {}),
    )


def _message_from_dict(data: dict[str, Any]) -> Message:
    return Message(
        id=data["id"],
        conversation_id=data["conversation_id"],
        role=data["role"],
        content=data["content"],
        created_at=from_iso(data["created_at"]),
        task_id=data.get("task_id"),
        metadata=dict(data.get("metadata") or {}),
    )


def _artifact_from_dict(data: dict[str, Any]) -> Artifact:
    return Artifact(
        id=data["id"],
        type=data["type"],
        title=data["title"],
        project_id=data["project_id"],
        conversation_id=data.get("conversation_id"),
        task_id=data["task_id"],
        report_id=data.get("report_id"),
        url=data["url"],
        version=data.get("version", 1),
        created_at=from_iso(data["created_at"]),
        metadata=dict(data.get("metadata") or {}),
    )


def _entity_dict(entity: Any) -> dict[str, Any]:
    data = asdict(entity)
    for key in ("created_at", "updated_at"):
        if key in data and hasattr(data[key], "isoformat"):
            data[key] = data[key].isoformat()
    return data


class ProjectStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        base = base_dir or DATA_DIR
        self._store = JsonFileStore(base / "projects.json")

    def create_project(self, project: AnalysisProject) -> AnalysisProject:
        def _create(data: dict[str, Any]) -> AnalysisProject:
            if project.id in data:
                raise DuplicateIdError(project.id)
            data[project.id] = _entity_dict(project)
            return project

        return self._store.mutate(_create)

    def get_project(self, project_id: str) -> AnalysisProject | None:
        raw = self._store.load().get(project_id)
        return _project_from_dict(raw) if raw else None

    def list_projects(self) -> list[AnalysisProject]:
        items = [_project_from_dict(v) for v in self._store.load().values()]
        return sorted(items, key=lambda p: p.updated_at, reverse=True)

    def update_project(self, project: AnalysisProject) -> AnalysisProject:
        def _update(data: dict[str, Any]) -> AnalysisProject:
            if project.id not in data:
                raise NotFoundError(project.id)
            data[project.id] = _entity_dict(project)
            return project

        return self._store.mutate(_update)

    def delete_project(self, project_id: str) -> None:
        def _delete(data: dict[str, Any]) -> None:
            if project_id not in data:
                raise NotFoundError(project_id)
            del data[project_id]

        self._store.mutate(_delete)


class ConversationStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        base = base_dir or DATA_DIR
        self._store = JsonFileStore(base / "conversations.json")

    def create_conversation(self, conversation: Conversation) -> Conversation:
        def _create(data: dict[str, Any]) -> Conversation:
            if conversation.id in data:
                raise DuplicateIdError(conversation.id)
            data[conversation.id] = _entity_dict(conversation)
            return conversation

        return self._store.mutate(_create)

    def get_conversation(self, conversation_id: str) -> Conversation | None:
        raw = self._store.load().get(conversation_id)
        return _conversation_from_dict(raw) if raw else None

    def list_conversations_by_project(self, project_id: str) -> list[Conversation]:
        items = [
            _conversation_from_dict(v)
            for v in self._store.load().values()
            if v.get("project_id") == project_id
        ]
        return sorted(items, key=lambda c: c.updated_at, reverse=True)

    def update_conversation(self, conversation: Conversation) -> Conversation:
        def _update(data: dict[str, Any]) -> Conversation:
            if conversation.id not in data:
                raise NotFoundError(conversation.id)
            data[conversation.id] = _entity_dict(conversation)
            return conversation

        return self._store.mutate(_update)

    def delete_conversations_by_project(self, project_id: str) -> list[str]:
        deleted_ids: list[str] = []

        def _delete(data: dict[str, Any]) -> list[str]:
            for cid, raw in list(data.items()):
                if raw.get("project_id") == project_id:
                    deleted_ids.append(cid)
                    del data[cid]
            return deleted_ids

        return self._store.mutate(_delete)


class MessageStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        base = base_dir or DATA_DIR
        self._store = JsonFileStore(base / "messages.json")

    def append_message(self, message: Message) -> Message:
        def _append(data: dict[str, Any]) -> Message:
            if message.id in data:
                raise DuplicateIdError(message.id)
            data[message.id] = _entity_dict(message)
            return message

        return self._store.mutate(_append)

    def get_message(self, message_id: str) -> Message | None:
        raw = self._store.load().get(message_id)
        return _message_from_dict(raw) if raw else None

    def list_messages_by_conversation(self, conversation_id: str) -> list[Message]:
        items = [
            _message_from_dict(v)
            for v in self._store.load().values()
            if v.get("conversation_id") == conversation_id
        ]
        return sorted(items, key=lambda m: m.created_at)

    def delete_messages_by_conversation_ids(self, conversation_ids: list[str]) -> list[str]:
        id_set = set(conversation_ids)
        task_ids: list[str] = []

        def _delete(data: dict[str, Any]) -> list[str]:
            for mid, raw in list(data.items()):
                if raw.get("conversation_id") in id_set:
                    tid = raw.get("task_id")
                    if tid:
                        task_ids.append(str(tid))
                    del data[mid]
            return task_ids

        return self._store.mutate(_delete)


class ArtifactStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        base = base_dir or DATA_DIR
        self._store = JsonFileStore(base / "artifacts.json")

    def create_artifact(self, artifact: Artifact) -> Artifact:
        def _create(data: dict[str, Any]) -> Artifact:
            if artifact.id in data:
                raise DuplicateIdError(artifact.id)
            data[artifact.id] = _entity_dict(artifact)
            return artifact

        return self._store.mutate(_create)

    def get_artifact(self, artifact_id: str) -> Artifact | None:
        raw = self._store.load().get(artifact_id)
        return _artifact_from_dict(raw) if raw else None

    def list_artifacts(
        self,
        *,
        project_id: str | None = None,
        conversation_id: str | None = None,
        task_id: str | None = None,
    ) -> list[Artifact]:
        items = [_artifact_from_dict(v) for v in self._store.load().values()]
        if project_id:
            items = [a for a in items if a.project_id == project_id]
        if conversation_id:
            items = [a for a in items if a.conversation_id == conversation_id]
        if task_id:
            items = [a for a in items if a.task_id == task_id]
        return sorted(items, key=lambda a: a.created_at, reverse=True)

    def get_or_create_report_artifact_v1(self, artifact: Artifact) -> Artifact:
        def _upsert(data: dict[str, Any]) -> Artifact:
            for existing in data.values():
                if (
                    existing.get("task_id") == artifact.task_id
                    and existing.get("type") == "report"
                    and existing.get("version") == 1
                ):
                    return _artifact_from_dict(existing)
            stable_id = stable_report_artifact_id(artifact.task_id)
            if stable_id in data:
                return _artifact_from_dict(data[stable_id])
            data[artifact.id] = _entity_dict(artifact)
            return artifact

        return self._store.mutate(_upsert)

    def get_or_create_evidence_artifact_v1(self, artifact: Artifact) -> Artifact:
        def _upsert(data: dict[str, Any]) -> Artifact:
            for existing in data.values():
                if (
                    existing.get("task_id") == artifact.task_id
                    and existing.get("type") == "evidence_package"
                    and existing.get("version") == 1
                ):
                    return _artifact_from_dict(existing)
            stable_id = stable_evidence_artifact_id(artifact.task_id)
            if stable_id in data:
                return _artifact_from_dict(data[stable_id])
            data[artifact.id] = _entity_dict(artifact)
            return artifact

        return self._store.mutate(_upsert)

    def delete_artifacts_by_project(self, project_id: str) -> list[str]:
        task_ids: list[str] = []

        def _delete(data: dict[str, Any]) -> list[str]:
            for aid, raw in list(data.items()):
                if raw.get("project_id") == project_id:
                    tid = raw.get("task_id")
                    if tid:
                        task_ids.append(str(tid))
                    del data[aid]
            return task_ids

        return self._store.mutate(_delete)


def new_id() -> str:
    return str(uuid4())
