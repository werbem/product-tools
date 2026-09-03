"""PR-V34: single-worker long-task busy gate + intent timeout anti-starve."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.workflow_launch_dto import WorkflowLaunchResult
from app.application.services.conversation_service import ConversationService
from app.application.services.follow_up_service import FollowUpResult
from app.application.services.intent_understanding_service import IntentUnderstandingService
from app.application.services.project_service import ProjectService
from app.application.services.simple_query_service import SimpleQueryResult
from app.application.services.simple_question_service import SimpleQuestionResult
from app.application.services.workflow_busy import (
    find_busy_long_task,
    resolve_busy,
)
from app.domain.entities.message import Message
from app.infrastructure.persistence import task_report_runtime
from app.infrastructure.persistence.copilot.stores import (
    ConversationStore,
    MessageStore,
    ProjectStore,
    new_id,
)
from app.domain.entities.copilot_common import utc_now
from app.application.dto.intent_dto import IntentUnderstandingRequest


def _intent(**kwargs) -> IntentUnderstandingResult:
    base = dict(
        type="competitive_analysis",
        company="飞猪",
        competitors=["美团"],
        product="酒店",
        objective="product_improvement",
        confidence=0.9,
        needs_clarification=False,
        raw_message="对比飞猪和美团酒店",
    )
    base.update(kwargs)
    return IntentUnderstandingResult(**base)  # type: ignore[arg-type]


@pytest.fixture
def services(tmp_path: Path, monkeypatch):
    persistence = tmp_path / "persistence"
    persistence.mkdir()
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.stores.DATA_DIR",
        persistence,
    )
    # Isolate task runtime between tests
    tasks: dict = {}
    monkeypatch.setattr(task_report_runtime, "_tasks", tasks)
    monkeypatch.setattr(task_report_runtime, "persist_tasks", lambda: None)

    project_store = ProjectStore()
    conversation_store = ConversationStore()
    message_store = MessageStore()
    project_service = ProjectService(store=project_store)
    intent_service = AsyncMock()
    deep = AsyncMock()
    deep.launch = AsyncMock(
        return_value=WorkflowLaunchResult(task_id="new-deep", report_id="new-deep", status="pending"),
    )
    deep.has_in_process_tasks = MagicMock(return_value=False)
    deep._running = set()
    collection = AsyncMock()
    collection.launch = AsyncMock(
        return_value=WorkflowLaunchResult(task_id="new-col", report_id="new-col", status="pending"),
    )
    collection.has_in_process_tasks = MagicMock(return_value=False)
    collection._running = set()

    simple_query = AsyncMock()
    simple_query.answer = AsyncMock(
        return_value=SimpleQueryResult(
            answer_markdown="查询短答：美团酒店近期公开动态有限。",
            sources=[],
            confidence=0.5,
            metadata={},
        ),
    )
    simple_question = AsyncMock()
    simple_question.answer = AsyncMock(
        return_value=SimpleQuestionResult(
            answer_markdown="- 积分互通需注意（内部笔记）",
            sources=[],
            confidence=0.7,
            question_mode="brief",
            metadata={},
        ),
    )
    follow_up = AsyncMock()

    svc = ConversationService(
        conversation_store=conversation_store,
        message_store=message_store,
        project_service=project_service,
        intent_service=intent_service,
        workflow_launcher=deep,
        collection_launcher=collection,
        simple_query_service=simple_query,
        simple_question_service=simple_question,
        follow_up_service=follow_up,
    )
    return {
        "svc": svc,
        "project_service": project_service,
        "intent": intent_service,
        "deep": deep,
        "collection": collection,
        "simple_query": simple_query,
        "simple_question": simple_question,
        "follow_up": follow_up,
        "message_store": message_store,
        "tasks": tasks,
    }


def _seed_busy(tasks: dict, *, project_id: str, task_id: str = "busy-deep-1", kind: str = "deep_analysis") -> None:
    entry = {
        "task_id": task_id,
        "status": "pending",
        "project_id": project_id,
        "state": {
            "current_phase": "researched",
            "progress": 40.0,
            "user_input": {"optional": {"workflow_kind": kind}},
        },
    }
    if kind == "intelligence_collection":
        entry["workflow_kind"] = kind
    tasks[task_id] = entry


class TestWorkflowBusyHelpers:
    def test_find_busy_global(self) -> None:
        tasks = {
            "a": {"task_id": "a", "status": "completed", "state": {}},
            "b": {
                "task_id": "b",
                "status": "pending",
                "project_id": "p1",
                "state": {"current_phase": "planned"},
            },
        }
        busy = find_busy_long_task(tasks=tasks)
        assert busy is not None
        assert busy.task_id == "b"

    def test_completed_not_busy(self) -> None:
        tasks = {"a": {"task_id": "a", "status": "completed", "workflow_kind": "deep_analysis"}}
        assert find_busy_long_task(tasks=tasks) is None

    def test_resolve_busy_in_process(self) -> None:
        deep = MagicMock()
        deep._running = {object()}
        deep.has_in_process_tasks = MagicMock(return_value=True)
        busy = resolve_busy(deep_launcher=deep, tasks={})
        assert busy is not None
        assert busy.task_id == "in-process"


class TestBusyGateConversation:
    @pytest.mark.asyncio
    async def test_busy_blocks_competitive_analysis(self, services) -> None:
        s = services
        project = s["project_service"].create_project("Busy CA")
        conv = s["svc"].create_conversation(project.id, title="c1")
        _seed_busy(s["tasks"], project_id=project.id)
        s["intent"].understand = AsyncMock(return_value=_intent())

        result = await s["svc"].process_user_message(conv.id, "对比一下飞猪和美团酒店")
        assert result.status == "workflow_busy"
        assert result.task_id is None
        assert "busy-deep-1" in result.assistant_message.content
        assert result.assistant_message.metadata.get("message_type") == "workflow_busy"
        s["deep"].launch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_busy_allows_information_query(self, services) -> None:
        s = services
        project = s["project_service"].create_project("Busy Q")
        conv = s["svc"].create_conversation(project.id)
        _seed_busy(s["tasks"], project_id=project.id)
        s["intent"].understand = AsyncMock(
            return_value=_intent(raw_message="美团酒店最近有什么变化？"),
        )

        result = await s["svc"].process_user_message(conv.id, "美团酒店最近有什么变化？")
        assert result.status == "query_answered"
        s["deep"].launch.assert_not_awaited()
        s["collection"].launch.assert_not_awaited()
        s["simple_query"].answer.assert_awaited()

    @pytest.mark.asyncio
    async def test_busy_allows_simple_question(self, services) -> None:
        s = services
        project = s["project_service"].create_project("Busy SQ")
        conv = s["svc"].create_conversation(project.id)
        _seed_busy(s["tasks"], project_id=project.id)
        s["intent"].understand = AsyncMock(
            return_value=_intent(raw_message="会员体系有什么注意点？"),
        )

        result = await s["svc"].process_user_message(conv.id, "会员体系有什么注意点？")
        assert result.status == "question_answered"
        assert "内部笔记" in result.assistant_message.content or "注意" in result.assistant_message.content
        s["deep"].launch.assert_not_awaited()
        s["simple_question"].answer.assert_awaited()

    @pytest.mark.asyncio
    async def test_busy_blocks_follow_up_upgrade(self, services) -> None:
        s = services
        project = s["project_service"].create_project("Busy FU")
        conv = s["svc"].create_conversation(project.id)
        _seed_busy(s["tasks"], project_id=project.id)
        # Seed prior analysis message so follow_up can upgrade
        s["message_store"].append_message(
            Message(
                id=new_id(),
                conversation_id=conv.id,
                role="assistant",
                content="已启动",
                task_id="prior-1",
                metadata={
                    "message_type": "analysis_started",
                    "workflow_type": "deep_analysis",
                    "validated_input": {
                        "our_company": "飞猪",
                        "competitor_company": "美团",
                        "product": "酒店",
                    },
                    "intent": _intent().model_dump(),
                },
                created_at=utc_now(),
            ),
        )
        s["intent"].understand = AsyncMock(
            return_value=_intent(raw_message="请基于刚才内容出一份完整竞品分析报告"),
        )
        s["follow_up"].handle = AsyncMock(
            return_value=FollowUpResult(
                answer_markdown="",
                follow_up_mode="upgrade_analysis",
                upgrade_to_analysis=True,
                prior_task_id="prior-1",
                prior_report_id="prior-1",
                context_summary="prior summary",
            ),
        )

        result = await s["svc"].process_user_message(
            conv.id, "请基于刚才内容出一份完整竞品分析报告",
        )
        assert result.status == "workflow_busy"
        assert result.assistant_message.metadata.get("follow_up_mode") == "upgrade_blocked_busy"
        s["deep"].launch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_idle_launches_deep(self, services) -> None:
        s = services
        project = s["project_service"].create_project("Idle CA")
        conv = s["svc"].create_conversation(project.id)
        assert find_busy_long_task(tasks=s["tasks"]) is None
        s["intent"].understand = AsyncMock(return_value=_intent())

        result = await s["svc"].process_user_message(conv.id, "对比飞猪和美团酒店，给出产品策略建议")
        assert result.status == "analysis_started"
        assert result.task_id == "new-deep"
        s["deep"].launch.assert_awaited_once()


class TestIntentTimeoutNoMislaunch:
    @pytest.mark.asyncio
    async def test_intent_timeout_uses_heuristic_not_crash(self, monkeypatch) -> None:
        monkeypatch.setenv("INTENT_LLM_TIMEOUT_S", "15")
        llm = AsyncMock()

        async def _slow(*_a, **_k):
            raise asyncio.TimeoutError("intent mock timeout")

        llm.generate = _slow
        svc = IntentUnderstandingService(llm_client_param=llm)
        result = await svc.understand(
            IntentUnderstandingRequest(message="会员体系有什么注意点？", conversation_id="c1"),
        )
        # Heuristic should not invent a full competitive launch envelope blindly;
        # brief Q without peer companies → unsupported or clarification.
        assert result.type in ("unsupported", "competitive_analysis")
        if result.type == "competitive_analysis":
            # Must not silently claim high-confidence Deep-ready entities from this Q alone
            assert result.needs_clarification or not (result.company and result.competitors and result.product)

    @pytest.mark.asyncio
    async def test_intent_timeout_does_not_launch_deep_on_simple_q(self, services, monkeypatch) -> None:
        s = services
        project = s["project_service"].create_project("Intent TO")
        conv = s["svc"].create_conversation(project.id)

        # Real intent service with timeouting LLM, but keep busy gate idle
        llm = AsyncMock()

        async def _boom(*_a, **_k):
            raise asyncio.TimeoutError("x")

        llm.generate = _boom
        s["svc"]._intent_service = IntentUnderstandingService(llm_client_param=llm)

        result = await s["svc"].process_user_message(conv.id, "会员体系有什么注意点？")
        s["deep"].launch.assert_not_awaited()
        s["collection"].launch.assert_not_awaited()
        # Prefer short-answer path or clarification — never silent analysis_started
        assert result.status != "analysis_started"
