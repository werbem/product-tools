"""Conversations API routes."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.application.dto.conversation_event_dto import ConversationEvent
from app.application.dto.copilot_api_dto import (
    ConversationResponse,
    ConversationTurnResponse,
    MessageResponse,
    SendMessageRequest,
)
from app.application.exceptions import (
    ConversationNotFoundError,
    ProjectArchivedError,
    ProjectNotFoundError,
)
from app.application.services.conversation_service import ConversationService
from app.infrastructure.events.conversation_event_bus import ConversationEventBus, get_conversation_event_bus
from app.interfaces.api.dependencies.copilot import get_conversation_service
from app.interfaces.api.mappers.copilot_mapper import (
    to_conversation_response,
    to_message_response,
    to_turn_response,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationResponse:
    try:
        return to_conversation_response(service.get_conversation(conversation_id))
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
def list_messages(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
) -> list[MessageResponse]:
    try:
        return [to_message_response(m) for m in service.get_messages(conversation_id)]
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")


@router.post("/{conversation_id}/messages", response_model=ConversationTurnResponse)
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> ConversationTurnResponse:
    try:
        result = await service.process_user_message(
            conversation_id,
            body.content,
            analysis_mode=body.analysis_mode,
        )
        return to_turn_response(result)
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")
    except ProjectNotFoundError:
        raise HTTPException(status_code=404, detail="项目不存在")
    except ProjectArchivedError:
        raise HTTPException(status_code=409, detail="项目已归档")


async def iter_conversation_sse_events(
    conversation_id: str,
    event_bus: ConversationEventBus,
) -> StreamingResponse:
    async def generator():
        connected = ConversationEvent(
            event="connected",
            conversation_id=conversation_id,
            timestamp=datetime.now(timezone.utc),
            data={"replay_supported": False},
        )
        yield f"event: connected\ndata: {json.dumps(connected.model_dump(mode='json'), ensure_ascii=False)}\n\n"
        async for event in event_bus.subscribe(conversation_id):
            payload = event.model_dump(mode="json")
            yield f"event: {event.event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{conversation_id}/stream")
async def stream_conversation(
    conversation_id: str,
    service: ConversationService = Depends(get_conversation_service),
    event_bus: ConversationEventBus = Depends(get_conversation_event_bus),
):
    try:
        service.get_conversation(conversation_id)
    except ConversationNotFoundError:
        raise HTTPException(status_code=404, detail="会话不存在")
    return await iter_conversation_sse_events(conversation_id, event_bus)
