"""Copilot API response mappers."""

from __future__ import annotations

from typing import Literal

from app.application.dto.copilot_api_dto import (
    ArtifactResponse,
    ConversationResponse,
    ConversationTurnResponse,
    MessageResponse,
    ProjectResponse,
)
from app.application.dto.conversation_dto import ConversationTurnResult
from app.domain.entities.analysis_project import AnalysisProject
from app.domain.entities.artifact import Artifact
from app.domain.entities.conversation import Conversation
from app.domain.entities.copilot_common import to_iso
from app.domain.entities.message import Message
from app.infrastructure.persistence import task_report_runtime

AnalysisStatus = Literal["idle", "running", "completed", "failed"]


def resolve_project_analysis_status(project_id: str) -> AnalysisStatus:
    """Derive latest analysis status from tasks linked to the project."""
    linked = [
        entry
        for entry in task_report_runtime.get_tasks().values()
        if entry.get("project_id") == project_id
    ]
    if not linked:
        return "idle"

    def _sort_key(entry: dict) -> str:
        state = entry.get("state") or {}
        return str(state.get("updated_at") or state.get("created_at") or "")

    linked.sort(key=_sort_key, reverse=True)
    status = str(linked[0].get("status") or "").lower()
    if status == "completed":
        return "completed"
    if status == "failed":
        return "failed"
    if status in {"pending", "running"}:
        return "running"
    return "idle"


def to_project_response(project: AnalysisProject) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        title=project.title,
        objective=project.objective,
        status=project.status,
        analysis_status=resolve_project_analysis_status(project.id),
        created_at=to_iso(project.created_at),
        updated_at=to_iso(project.updated_at),
        metadata=project.metadata,
    )


def to_conversation_response(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        project_id=conversation.project_id,
        title=conversation.title,
        status=conversation.status,
        created_at=to_iso(conversation.created_at),
        updated_at=to_iso(conversation.updated_at),
        metadata=conversation.metadata,
    )


def to_message_response(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        created_at=to_iso(message.created_at),
        task_id=message.task_id,
        metadata=message.metadata,
    )


def to_turn_response(result: ConversationTurnResult) -> ConversationTurnResponse:
    return ConversationTurnResponse(
        conversation=to_conversation_response(result.conversation),
        user_message=to_message_response(result.user_message),
        assistant_message=to_message_response(result.assistant_message),
        intent=result.intent,
        status=result.status,
        task_id=result.task_id,
        report_id=result.report_id,
        routing_decision=result.routing_decision,
    )


def to_artifact_response(artifact: Artifact) -> ArtifactResponse:
    download_url = artifact.metadata.get("download_url")
    return ArtifactResponse(
        id=artifact.id,
        type=artifact.type,
        title=artifact.title,
        project_id=artifact.project_id,
        conversation_id=artifact.conversation_id,
        task_id=artifact.task_id,
        report_id=artifact.report_id,
        url=artifact.url,
        download_url=str(download_url) if download_url else None,
        version=artifact.version,
        created_at=to_iso(artifact.created_at),
        metadata=artifact.metadata,
    )
