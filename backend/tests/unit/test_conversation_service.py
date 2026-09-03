"""Unit tests for ConversationService."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.application.dto.intent_dto import IntentUnderstandingRequest, IntentUnderstandingResult
from app.application.exceptions import ConversationNotFoundError
from app.application.services.conversation_service import ConversationService
from app.application.services.project_service import ProjectService
from app.infrastructure.persistence.copilot.stores import ConversationStore, MessageStore, ProjectStore


@pytest.fixture
def services(tmp_path: Path, monkeypatch):
    persistence = tmp_path / "persistence"
    persistence.mkdir()
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.stores.DATA_DIR",
        persistence,
    )
    project_store = ProjectStore()
    conversation_store = ConversationStore()
    message_store = MessageStore()
    project_service = ProjectService(store=project_store)
    intent_service = AsyncMock()
    conversation_service = ConversationService(
        conversation_store=conversation_store,
        message_store=message_store,
        project_service=project_service,
        intent_service=intent_service,
    )
    return conversation_service, project_service, intent_service


class TestConversationService:
    def test_create_conversation(self, services) -> None:
        conversation_service, project_service, _ = services
        project = project_service.create_project("P1")
        conversation = conversation_service.create_conversation(project.id, title="C1")
        assert conversation.project_id == project.id
        assert conversation.title == "C1"

    def test_get_missing_conversation_raises(self, services) -> None:
        conversation_service, _, _ = services
        with pytest.raises(ConversationNotFoundError):
            conversation_service.get_conversation("missing")

    @pytest.mark.asyncio
    async def test_process_message_needs_clarification(self, services) -> None:
        conversation_service, project_service, intent_service = services
        project = project_service.create_project("P1")
        conversation = conversation_service.create_conversation(project.id)

        intent_service.understand = AsyncMock(
            return_value=IntentUnderstandingResult(
                type="competitive_analysis",
                company="飞猪",
                competitors=["美团"],
                product="酒店",
                objective="product_improvement",
                confidence=0.8,
                needs_clarification=True,
                clarification_question="请补充信息",
                raw_message="测试",
            ),
        )

        result = await conversation_service.process_user_message(conversation.id, "测试")
        assert result.status == "needs_clarification"
        assert result.task_id is None
        messages = conversation_service.get_messages(conversation.id)
        assert len(messages) == 2
        intent_service.understand.assert_awaited_once()
        call_arg = intent_service.understand.await_args.args[0]
        assert isinstance(call_arg, IntentUnderstandingRequest)
