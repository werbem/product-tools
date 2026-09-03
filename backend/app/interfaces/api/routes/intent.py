"""Intent API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.application.dto.intent_dto import IntentUnderstandingRequest, IntentUnderstandingResult
from app.application.services.intent_understanding_service import IntentUnderstandingService
from app.interfaces.api.dependencies.copilot import get_intent_understanding_service

router = APIRouter(prefix="/intent", tags=["intent"])


@router.post("/understand", response_model=IntentUnderstandingResult)
async def understand_intent(
    body: IntentUnderstandingRequest,
    service: IntentUnderstandingService = Depends(get_intent_understanding_service),
) -> IntentUnderstandingResult:
    return await service.understand(body)
