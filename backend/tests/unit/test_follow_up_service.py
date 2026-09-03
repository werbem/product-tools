"""Phase 2 Step 4: follow_up routing + FollowUpService."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext
from app.application.dto.workflow_launch_dto import WorkflowLaunchResult
from app.application.services.conversation_service import ConversationService
from app.application.services.follow_up_service import (
    FollowUpService,
    message_has_prior_artifact,
)
from app.application.services.project_service import ProjectService
from app.application.services.router_service import RouterService
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


class TestFollowUpRouter:
    def setup_method(self) -> None:
        self.router = RouterService()

    def test_follow_up_with_prior(self) -> None:
        raw = "基于刚才结果，定价策略上我们该怎么做？"
        d = self.router.route(
            _intent(raw=raw),
            raw,
            ConversationRoutingContext(has_prior_analysis=True),
        )
        assert d.workflow_type == "follow_up"
        assert d.reason == "follow_up_with_prior_context"

    def test_follow_up_without_prior(self) -> None:
        raw = "基于刚才结果看定价"
        d = self.router.route(
            _intent(raw=raw),
            raw,
            ConversationRoutingContext(has_prior_analysis=False),
        )
        assert d.workflow_type == "follow_up"
        assert d.reason == "follow_up_no_prior"

    def test_light_query_still_information_query(self) -> None:
        raw = "美团酒店最近有什么变化"
        d = self.router.route(
            _intent(company="美团", competitors=[], product="酒店", raw=raw),
            raw,
            ConversationRoutingContext(has_prior_analysis=True),
        )
        assert d.workflow_type == "information_query"

    def test_upgrade_phrase_still_follow_up_not_legacy_deep(self) -> None:
        raw = "继续，把会员体系也对比一下并出完整报告"
        d = self.router.route(
            _intent(raw=raw),
            raw,
            ConversationRoutingContext(has_prior_analysis=True),
        )
        assert d.workflow_type == "follow_up"


class TestFollowUpService:
    def test_short_answer_with_fake_llm(self) -> None:
        async def fake_llm(**kwargs):
            assert "上轮" in kwargs["user_prompt"] or "上下文" in kwargs["user_prompt"]
            return LLMResponse(content="- 建议保持价格带清晰\n- 可参考上轮证据中的会员权益")

        msgs = [
            Message(
                id=new_id(),
                conversation_id="c1",
                role="assistant",
                content="分析已启动",
                task_id="task-prior",
                metadata={
                    "message_type": "analysis_started",
                    "report_id": "rep-prior",
                    "intent": _intent().model_dump(),
                },
                created_at=utc_now(),
            ),
        ]
        assert message_has_prior_artifact(msgs)
        svc = FollowUpService(llm_generate=fake_llm)
        result = asyncio.run(
            svc.handle(
                query="基于刚才结果，定价策略上我们该怎么做？",
                intent=_intent(),
                messages=msgs,
                conversation_id="c1",
            )
        )
        assert not result.upgrade_to_analysis
        assert result.follow_up_mode == "short_answer"
        assert result.prior_task_id == "task-prior"
        assert "价格" in result.answer_markdown or "会员" in result.answer_markdown

    def test_upgrade_detects_full_report(self) -> None:
        msgs = [
            Message(
                id=new_id(),
                conversation_id="c1",
                role="assistant",
                content="x",
                task_id="t1",
                metadata={"message_type": "analysis_started", "report_id": "r1"},
                created_at=utc_now(),
            ),
        ]
        svc = FollowUpService(llm_generate=AsyncMock())
        result = asyncio.run(
            svc.handle(
                query="继续，把会员体系也对比一下并出完整报告",
                intent=_intent(),
                messages=msgs,
            )
        )
        assert result.upgrade_to_analysis
        assert result.follow_up_mode == "upgrade_analysis"
        assert result.context_summary

    def test_no_prior_clarify(self) -> None:
        svc = FollowUpService(llm_generate=AsyncMock())
        result = asyncio.run(
            svc.handle(
                query="基于刚才结果看定价",
                intent=_intent(),
                messages=[],
            )
        )
        assert result.follow_up_mode == "no_prior"
        assert not result.upgrade_to_analysis
        assert "没有可追问" in result.answer_markdown or "请先" in result.answer_markdown


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
    svc = ConversationService(
        conversation_store=conversation_store,
        message_store=message_store,
        project_service=project_service,
        intent_service=intent_service,
        workflow_launcher=deep,
        collection_launcher=collect,
        router_service=RouterService(),
        follow_up_service=FollowUpService(
            llm_generate=AsyncMock(
                return_value=LLMResponse(content="- 基于上轮：维持差异化定价"),
            ),
        ),
    )
    return svc, project_service, intent_service, deep, collect, message_store


class TestConversationFollowUpDispatch:
    def _seed_prior(self, message_store: MessageStore, conversation_id: str) -> None:
        message_store.append_message(
            Message(
                id=new_id(),
                conversation_id=conversation_id,
                role="assistant",
                content="已启动分析",
                task_id="prior-task",
                metadata={
                    "message_type": "analysis_started",
                    "report_id": "prior-rep",
                    "workflow_type": "deep_analysis",
                    "intent": _intent().model_dump(),
                },
                created_at=utc_now(),
            ),
        )

    def test_short_follow_up_no_deep(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect, message_store = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        self._seed_prior(message_store, conversation.id)
        raw = "基于刚才结果，定价策略上我们该怎么做？"
        intent_service.understand = AsyncMock(return_value=_intent(raw=raw))
        result = asyncio.run(svc.process_user_message(conversation.id, raw))
        assert result.status == "follow_up_answered"
        assert result.task_id is None
        assert result.routing_decision.workflow_type == "follow_up"
        deep.launch.assert_not_awaited()
        collect.launch.assert_not_awaited()
        meta = result.assistant_message.metadata or {}
        assert meta["follow_up_mode"] == "short_answer"
        assert meta["prior_task_id"] == "prior-task"

    def test_upgrade_calls_deep_once(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect, message_store = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        self._seed_prior(message_store, conversation.id)
        raw = "继续，把会员体系也对比一下并出完整报告"
        intent_service.understand = AsyncMock(return_value=_intent(raw=raw))
        result = asyncio.run(svc.process_user_message(conversation.id, raw, analysis_mode="full"))
        assert result.status == "analysis_started"
        assert result.task_id == "task-deep"
        deep.launch.assert_awaited_once()
        collect.launch.assert_not_awaited()
        meta = result.assistant_message.metadata or {}
        assert meta["follow_up_mode"] == "upgrade_analysis"
        # scene should carry follow-up context
        req = deep.launch.await_args.args[0]
        assert "追问" in (req.scene or "") or (req.optional or {}).get("follow_up")

    def test_follow_up_no_prior_no_deep(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect, _message_store = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        raw = "基于刚才结果看定价"
        intent_service.understand = AsyncMock(return_value=_intent(raw=raw))
        result = asyncio.run(svc.process_user_message(conversation.id, raw))
        assert result.status == "follow_up_answered"
        assert result.task_id is None
        deep.launch.assert_not_awaited()
        assert "请先" in result.assistant_message.content or "没有可追问" in result.assistant_message.content
