"""Integration tests for intent API."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.interfaces.api.dependencies.copilot import get_intent_understanding_service


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    yield TestClient(app)
    app.dependency_overrides.clear()


class TestIntentAPI:
    def test_understand_intent(self, client: TestClient, monkeypatch) -> None:
        mock_result = IntentUnderstandingResult(
            type="competitive_analysis",
            company="飞猪",
            competitors=["美团", "携程"],
            product="酒店",
            objective="product_improvement",
            confidence=0.95,
            raw_message="分析飞猪酒店",
        )

        class _MockIntentService:
            understand = AsyncMock(return_value=mock_result)

        monkeypatch.setattr(
            "app.interfaces.api.dependencies.copilot.get_intent_understanding_service",
            lambda: _MockIntentService(),
        )
        get_intent_understanding_service.cache_clear()

        resp = client.post(
            "/api/intent/understand",
            json={"message": "分析飞猪酒店"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["company"] == "飞猪"
        assert data["type"] == "competitive_analysis"
