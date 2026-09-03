"""Phase 2 Step 5: simple_question router + service."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext
from app.application.dto.workflow_launch_dto import WorkflowLaunchResult
from app.application.services.conversation_service import ConversationService
from app.application.services.follow_up_service import FollowUpService
from app.application.services.project_service import ProjectService
from app.application.services.router_service import RouterService
from app.application.services.simple_question_service import SimpleQuestionService
from app.application.services.simple_query_service import QuerySource, SimpleQueryResult
from app.domain.entities.copilot_common import utc_now
from app.domain.entities.message import Message
from app.infrastructure.llm.client import LLMResponse
from app.infrastructure.persistence.copilot.stores import (
    ConversationStore,
    MessageStore,
    ProjectStore,
    new_id,
)


def _intent(**kwargs) -> IntentUnderstandingResult:
    base = dict(
        type="competitive_analysis",
        company="飞猪",
        competitors=["美团"],
        product="酒店",
        objective="product_improvement",
        confidence=0.9,
        needs_clarification=False,
        raw_message="placeholder",
    )
    if "raw" in kwargs:
        kwargs["raw_message"] = kwargs.pop("raw")
    if "type_" in kwargs:
        kwargs["type"] = kwargs.pop("type_")
    base.update(kwargs)
    if not base.get("raw_message"):
        base["raw_message"] = "placeholder"
    return IntentUnderstandingResult(**base)  # type: ignore[arg-type]


class TestSimpleQuestionRouter:
    def setup_method(self) -> None:
        self.router = RouterService()

    def test_what_is_company(self) -> None:
        raw = "飞猪是什么公司？"
        d = self.router.route(_intent(company="飞猪", raw=raw), raw)
        assert d.workflow_type == "simple_question"

    def test_prior_competitors_question(self) -> None:
        raw = "刚才报告里竞品是谁？"
        d = self.router.route(
            _intent(raw=raw),
            raw,
            ConversationRoutingContext(has_prior_analysis=True),
        )
        assert d.workflow_type == "simple_question"

    def test_dynamics_still_information_query(self) -> None:
        raw = "美团酒店最近有什么变化？"
        d = self.router.route(
            _intent(company="美团", competitors=[], product="酒店", raw=raw),
            raw,
        )
        assert d.workflow_type == "information_query"

    def test_follow_up_still_follow_up(self) -> None:
        raw = "基于刚才结果看定价"
        d = self.router.route(
            _intent(raw=raw),
            raw,
            ConversationRoutingContext(has_prior_analysis=True),
        )
        assert d.workflow_type == "follow_up"

    def test_full_report_still_competitive(self) -> None:
        raw = "请做飞猪与美团的完整竞品分析报告"
        d = self.router.route(
            _intent(competitors=["美团"], raw=raw),
            raw,
        )
        assert d.workflow_type == "competitive_analysis"


class TestSimpleQuestionService:
    def test_context_only_with_prior(self) -> None:
        async def fake_llm(**kwargs):
            return LLMResponse(content="- 上轮对比竞品为美团与携程")

        msgs = [
            Message(
                id=new_id(),
                conversation_id="c1",
                role="assistant",
                content="已完成分析，对比了美团与携程",
                task_id="t1",
                metadata={
                    "message_type": "analysis_started",
                    "report_id": "r1",
                    "intent": _intent().model_dump(),
                },
                created_at=utc_now(),
            ),
        ]
        svc = SimpleQuestionService(llm_generate=fake_llm)
        result = asyncio.run(
            svc.answer(
                query="刚才报告里竞品是谁？",
                intent=_intent(),
                messages=msgs,
            )
        )
        assert result.question_mode == "context_only"
        assert "美团" in result.answer_markdown or "竞品" in result.answer_markdown

    def test_light_search_with_company(self) -> None:
        async def fake_query_answer(**kwargs):
            return SimpleQueryResult(
                answer_markdown="飞猪是阿里巴巴旗下旅行平台。\n\n- [来源](https://ex.com/1)",
                sources=[QuerySource(title="来源", url="https://ex.com/1")],
                confidence=0.7,
                metadata={"hit_count": 1},
            )

        query_svc = AsyncMock()
        query_svc.answer = fake_query_answer
        svc = SimpleQuestionService(query_service=query_svc, llm_generate=AsyncMock())
        result = asyncio.run(
            svc.answer(
                query="飞猪是什么公司？",
                intent=_intent(company="飞猪", competitors=[], raw="飞猪是什么公司？"),
                messages=[],
            )
        )
        assert result.question_mode == "light_search"
        assert result.sources

    def test_guide_without_entity(self) -> None:
        svc = SimpleQuestionService(llm_generate=AsyncMock())
        result = asyncio.run(
            svc.answer(
                query="这是什么意思？",
                intent=_intent(company=None, product=None, competitors=[], raw="这是什么意思？"),
                messages=[],
            )
        )
        assert result.question_mode == "guide"
        assert "补充" in result.answer_markdown or "公司" in result.answer_markdown


@pytest.fixture
def conv_env(tmp_path: Path, monkeypatch):
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
    deep = AsyncMock()
    deep.launch = AsyncMock(
        return_value=WorkflowLaunchResult(task_id="task-deep", report_id="rep-deep"),
    )
    collect = AsyncMock()
    collect.launch = AsyncMock(
        return_value=WorkflowLaunchResult(task_id="task-collect", report_id="rep-collect"),
    )

    async def fake_sq_answer(**kwargs):
        return SimpleQueryResult(
            answer_markdown="飞猪是旅行平台。",
            sources=[QuerySource(title="t", url="https://ex.com/a")],
            confidence=0.6,
            metadata={},
        )

    query_svc = AsyncMock()
    query_svc.answer = fake_sq_answer

    svc = ConversationService(
        conversation_store=conversation_store,
        message_store=message_store,
        project_service=project_service,
        intent_service=intent_service,
        workflow_launcher=deep,
        collection_launcher=collect,
        router_service=RouterService(),
        simple_query_service=query_svc,
        follow_up_service=FollowUpService(
            llm_generate=AsyncMock(return_value=LLMResponse(content="- ok")),
        ),
        simple_question_service=SimpleQuestionService(
            query_service=query_svc,
            llm_generate=AsyncMock(return_value=LLMResponse(content="- 短答")),
        ),
    )
    return svc, project_service, intent_service, deep, collect, message_store


class TestConversationSimpleQuestion:
    def test_definition_no_launchers(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect, _ms = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        raw = "飞猪是什么公司？"
        intent_service.understand = AsyncMock(
            return_value=_intent(company="飞猪", competitors=[], raw=raw),
        )
        result = asyncio.run(svc.process_user_message(conversation.id, raw))
        assert result.status == "question_answered"
        assert result.task_id is None
        assert result.routing_decision.workflow_type == "simple_question"
        deep.launch.assert_not_awaited()
        collect.launch.assert_not_awaited()
        assert (result.assistant_message.metadata or {}).get("question_mode") in (
            "light_search",
            "context_only",
            "guide",
            "llm_only",
        )
