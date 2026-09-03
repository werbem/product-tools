"""Copilot HTTP API DTOs."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.application.dto.conversation_dto import TurnStatus
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import RoutingDecision


class CreateProjectRequest(BaseModel):
    title: str
    objective: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be empty")
        return stripped


class CreateConversationRequest(BaseModel):
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class SendMessageRequest(BaseModel):
    content: str
    analysis_mode: Literal["fast", "full"] = "fast"

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("content must not be empty")
        return stripped

    @field_validator("analysis_mode", mode="before")
    @classmethod
    def normalize_mode(cls, value: str | None) -> str:
        mode = (value or "fast").strip().lower()
        return "full" if mode == "full" else "fast"


class ProjectResponse(BaseModel):
    id: str
    title: str
    objective: str | None
    status: Literal["active", "archived"]
    analysis_status: Literal["idle", "running", "completed", "failed"] = "idle"
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


class ConversationResponse(BaseModel):
    id: str
    project_id: str
    title: str | None
    status: Literal["active", "completed", "archived"]
    created_at: str
    updated_at: str
    metadata: dict[str, Any]


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: Literal["user", "assistant", "system"]
    content: str
    created_at: str
    task_id: str | None
    metadata: dict[str, Any]


class ConversationTurnResponse(BaseModel):
    conversation: ConversationResponse
    user_message: MessageResponse
    assistant_message: MessageResponse
    intent: IntentUnderstandingResult
    status: TurnStatus
    task_id: str | None = None
    report_id: str | None = None
    routing_decision: RoutingDecision | None = None


class ArtifactResponse(BaseModel):
    id: str
    type: str
    title: str
    project_id: str
    conversation_id: str | None
    task_id: str
    report_id: str | None
    url: str
    download_url: str | None = None
    version: int
    created_at: str
    metadata: dict[str, Any]


class ProjectMemoryEntitiesDTO(BaseModel):
    our_company: str | None = None
    competitors: list[str] = Field(default_factory=list)
    product: str | None = None
    industry: str | None = None


class MemoryFindingDTO(BaseModel):
    text: str
    source_task_id: str | None = None
    source_type: Literal["report", "collection", "manual"] = "manual"
    updated_at: str


class ConversationMemorySummaryDTO(BaseModel):
    last_workflow_type: str | None = None
    summary: str = ""
    validated_input: dict[str, Any] | None = None
    updated_at: str


class ProjectMemoryResponse(BaseModel):
    project_id: str
    entities: ProjectMemoryEntitiesDTO
    last_objectives: list[str] = Field(default_factory=list)
    key_findings: list[MemoryFindingDTO] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    last_report_id: str | None = None
    last_collection_id: str | None = None
    last_task_id: str | None = None
    last_workflow_type: str | None = None
    conversation_summaries: dict[str, ConversationMemorySummaryDTO] = Field(default_factory=dict)
    schema_version: int = 1
    updated_at: str


class PatchProjectMemoryRequest(BaseModel):
    entities: ProjectMemoryEntitiesDTO | None = None
    open_questions: list[str] | None = None
    key_findings: list[str | MemoryFindingDTO] | None = None


class CreateKnowledgeNoteRequest(BaseModel):
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be empty")
        return stripped

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("body must not be empty")
        return stripped


class PatchKnowledgeNoteRequest(BaseModel):
    title: str | None = None
    body: str | None = None
    tags: list[str] | None = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("title must not be empty")
        return stripped

    @field_validator("body")
    @classmethod
    def validate_body(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("body must not be empty")
        return stripped


class KnowledgeNoteResponse(BaseModel):
    id: str
    project_id: str
    title: str
    body: str
    tags: list[str] = Field(default_factory=list)
    created_at: str
    updated_at: str
