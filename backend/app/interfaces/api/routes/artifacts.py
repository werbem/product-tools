"""Artifacts API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from app.application.dto.copilot_api_dto import ArtifactResponse
from app.application.exceptions import ArtifactNotFoundError
from app.application.services.artifact_service import ArtifactService
from app.interfaces.api.dependencies.workflow import get_artifact_service
from app.interfaces.api.mappers.copilot_mapper import to_artifact_response

router = APIRouter(prefix="/artifacts", tags=["artifacts"])


def _validate_filters(
    project_id: str | None,
    conversation_id: str | None,
    task_id: str | None,
) -> None:
    provided = sum(1 for v in (project_id, conversation_id, task_id) if v)
    if provided > 1:
        raise HTTPException(status_code=422, detail="只能指定一个过滤参数")


@router.get("", response_model=list[ArtifactResponse])
def list_artifacts(
    project_id: str | None = Query(default=None),
    conversation_id: str | None = Query(default=None),
    task_id: str | None = Query(default=None),
    service: ArtifactService = Depends(get_artifact_service),
) -> list[ArtifactResponse]:
    _validate_filters(project_id, conversation_id, task_id)
    artifacts = service.list_artifacts(
        project_id=project_id,
        conversation_id=conversation_id,
        task_id=task_id,
    )
    return [to_artifact_response(a) for a in artifacts]


@router.get("/{artifact_id}", response_model=ArtifactResponse)
def get_artifact(
    artifact_id: str,
    service: ArtifactService = Depends(get_artifact_service),
) -> ArtifactResponse:
    try:
        return to_artifact_response(service.get_artifact(artifact_id))
    except ArtifactNotFoundError:
        raise HTTPException(status_code=404, detail="文件不存在")
