"""Integration tests for Copilot conversation API (dependency wiring)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.interfaces.api.dependencies.copilot import (
    get_conversation_store,
    get_intent_understanding_service,
    get_message_store,
    get_project_store,
)


def _clear_copilot_caches() -> None:
    get_project_store.cache_clear()
    get_conversation_store.cache_clear()
    get_message_store.cache_clear()
    get_intent_understanding_service.cache_clear()
    from app.interfaces.api.dependencies.copilot import (
        get_knowledge_notes_store,
        get_knowledge_service,
        get_memory_service,
        get_memory_writer,
        get_project_memory_store,
        get_project_service,
    )
    from app.interfaces.api.dependencies.workflow import (
        get_artifact_store,
        get_collection_workflow_launcher,
        get_workflow_launcher,
    )

    get_project_memory_store.cache_clear()
    get_memory_writer.cache_clear()
    get_memory_service.cache_clear()
    get_knowledge_notes_store.cache_clear()
    get_knowledge_service.cache_clear()
    get_project_service.cache_clear()
    get_artifact_store.cache_clear()
    get_collection_workflow_launcher.cache_clear()
    get_workflow_launcher.cache_clear()


@pytest.fixture
def client(tmp_path, monkeypatch) -> TestClient:
    persistence = tmp_path / "persistence"
    persistence.mkdir()
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.stores.DATA_DIR",
        persistence,
    )
    _clear_copilot_caches()
    from app.main import app

    yield TestClient(app)
    app.dependency_overrides.clear()
    _clear_copilot_caches()


class TestConversationAPI:
    def test_create_project_and_conversation(self, client: TestClient) -> None:
        """Regression: get_collection_workflow_launcher must be imported in copilot deps."""
        project_resp = client.post(
            "/api/projects",
            json={"title": "Step29测试", "objective": "验收"},
        )
        assert project_resp.status_code == 201, project_resp.text
        project_id = project_resp.json()["id"]

        conv_resp = client.post(
            f"/api/projects/{project_id}/conversations",
            json={},
        )
        assert conv_resp.status_code == 201, conv_resp.text
        data = conv_resp.json()
        assert data["project_id"] == project_id
        assert "id" in data

    def test_send_message_without_dependency_error(self, client: TestClient, monkeypatch) -> None:
        mock_intent = AsyncMock(
            return_value=IntentUnderstandingResult(
                type="competitive_analysis",
                company="飞猪",
                competitors=["美团"],
                product="酒店",
                objective="product_improvement",
                confidence=0.9,
                needs_clarification=True,
                clarification_question="请补充更多背景信息。",
                raw_message="测试消息",
            ),
        )

        class _MockIntentService:
            understand = mock_intent

        monkeypatch.setattr(
            "app.interfaces.api.dependencies.copilot.get_intent_understanding_service",
            lambda: _MockIntentService(),
        )
        get_intent_understanding_service.cache_clear()

        project_resp = client.post(
            "/api/projects",
            json={"title": "Msg test", "objective": "验收"},
        )
        project_id = project_resp.json()["id"]
        conv_resp = client.post(f"/api/projects/{project_id}/conversations", json={})
        conversation_id = conv_resp.json()["id"]

        msg_resp = client.post(
            f"/api/conversations/{conversation_id}/messages",
            json={"content": "测试消息"},
        )
        assert msg_resp.status_code == 200, msg_resp.text
        body = msg_resp.json()
        assert body["status"] in (
            "needs_clarification",
            "analysis_started",
            "unsupported",
            "out_of_scope",
            "unsupported_workflow",
            "query_answered",
            "follow_up_answered",
            "question_answered",
        )
        assert body["conversation"]["id"] == conversation_id
