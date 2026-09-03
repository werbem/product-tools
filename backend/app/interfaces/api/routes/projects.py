"""Projects API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.application.dto.copilot_api_dto import (
    ConversationResponse,
    CreateConversationRequest,
    CreateKnowledgeNoteRequest,
    CreateProjectRequest,
    KnowledgeNoteResponse,
    PatchKnowledgeNoteRequest,
    PatchProjectMemoryRequest,
    ProjectMemoryResponse,
    ProjectResponse,
)
from app.application.exceptions import KnowledgeNoteNotFoundError, ProjectNotFoundError
from app.application.services.conversation_service import ConversationService
from app.application.services.knowledge_service import KnowledgeService
from app.application.services.memory_service import MemoryService
from app.application.services.project_service import ProjectService
from app.interfaces.api.dependencies.copilot import (
    get_conversation_service,
    get_knowledge_service,
    get_memory_service,
    get_project_service,
)
from app.interfaces.api.mappers.copilot_mapper import to_conversation_response, to_project_response

router = APIRouter(prefix="/projects", tags=["projects"])


def _note_response(note) -> KnowledgeNoteResponse:
    return KnowledgeNoteResponse(**note.to_dict())


@router.post("", response_model=ProjectResponse, status_code=201)
def create_project(
    body: CreateProjectRequest,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    project = service.create_project(body.title, body.objective, body.metadata)
    return to_project_response(project)


@router.get("", response_model=list[ProjectResponse])
def list_projects(
    service: ProjectService = Depends(get_project_service),
) -> list[ProjectResponse]:
    return [to_project_response(p) for p in service.list_projects()]


@router.get("/{project_id}", response_model=ProjectResponse)
def get_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    try:
        return to_project_response(service.get_project(project_id))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")


@router.get("/{project_id}/memory", response_model=ProjectMemoryResponse)
def get_project_memory(
    project_id: str,
    service: MemoryService = Depends(get_memory_service),
) -> ProjectMemoryResponse:
    """Return ProjectMemory; empty skeleton when never written."""
    try:
        memory = service.get_memory(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ProjectMemoryResponse(**memory.to_dict())


@router.patch("/{project_id}/memory", response_model=ProjectMemoryResponse)
def patch_project_memory(
    project_id: str,
    body: PatchProjectMemoryRequest,
    service: MemoryService = Depends(get_memory_service),
) -> ProjectMemoryResponse:
    try:
        memory = service.patch_memory(project_id, body.model_dump(exclude_unset=True))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
    return ProjectMemoryResponse(**memory.to_dict())


@router.get("/{project_id}/knowledge/notes", response_model=list[KnowledgeNoteResponse])
def list_knowledge_notes(
    project_id: str,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> list[KnowledgeNoteResponse]:
    try:
        return [_note_response(n) for n in service.list_notes(project_id)]
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")


@router.post(
    "/{project_id}/knowledge/notes",
    response_model=KnowledgeNoteResponse,
    status_code=201,
)
def create_knowledge_note(
    project_id: str,
    body: CreateKnowledgeNoteRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeNoteResponse:
    try:
        note = service.create_note(
            project_id, title=body.title, body=body.body, tags=body.tags,
        )
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _note_response(note)


@router.get(
    "/{project_id}/knowledge/notes/{note_id}",
    response_model=KnowledgeNoteResponse,
)
def get_knowledge_note(
    project_id: str,
    note_id: str,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeNoteResponse:
    try:
        return _note_response(service.get_note(project_id, note_id))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
    except KnowledgeNoteNotFoundError:
        raise HTTPException(status_code=404, detail="知识笔记不存在")


@router.patch(
    "/{project_id}/knowledge/notes/{note_id}",
    response_model=KnowledgeNoteResponse,
)
def patch_knowledge_note(
    project_id: str,
    note_id: str,
    body: PatchKnowledgeNoteRequest,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> KnowledgeNoteResponse:
    try:
        note = service.update_note(
            project_id, note_id, body.model_dump(exclude_unset=True),
        )
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
    except KnowledgeNoteNotFoundError:
        raise HTTPException(status_code=404, detail="知识笔记不存在")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _note_response(note)


@router.delete("/{project_id}/knowledge/notes/{note_id}", status_code=204)
def delete_knowledge_note(
    project_id: str,
    note_id: str,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> None:
    try:
        service.delete_note(project_id, note_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
    except KnowledgeNoteNotFoundError:
        raise HTTPException(status_code=404, detail="知识笔记不存在")


@router.get("/{project_id}/knowledge/search", response_model=list[KnowledgeNoteResponse])
def search_knowledge_notes(
    project_id: str,
    q: str = "",
    limit: int = 5,
    service: KnowledgeService = Depends(get_knowledge_service),
) -> list[KnowledgeNoteResponse]:
    if not (q or "").strip():
        raise HTTPException(status_code=422, detail="q must not be empty")
    try:
        return [
            _note_response(n)
            for n in service.search(project_id, q.strip(), limit=limit)
        ]
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")


@router.post("/{project_id}/archive", response_model=ProjectResponse)
def archive_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> ProjectResponse:
    try:
        return to_project_response(service.archive_project(project_id))
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")


@router.delete("/{project_id}")
def delete_project(
    project_id: str,
    service: ProjectService = Depends(get_project_service),
) -> dict:
    try:
        return service.delete_project(project_id)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")


@router.post("/{project_id}/conversations", response_model=ConversationResponse, status_code=201)
def create_conversation(
    project_id: str,
    body: CreateConversationRequest | None = None,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    req = body or CreateConversationRequest()
    try:
        conversation = service.create_conversation(project_id, req.title, req.metadata)
        return to_conversation_response(conversation)
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")


@router.get("/{project_id}/conversations", response_model=list[ConversationResponse])
def list_conversations(
    project_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> list[ConversationResponse]:
    try:
        return [to_conversation_response(c) for c in service.list_conversations(project_id)]
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
