"""Phase 2 Step 8: follow_up upgrade recovers prior analysis intent (DEF-E2).

Locks the Step 7 failure path:
  analysis_started (full entities) → follow_up short answer (empty intent)
  → upgrade phrase → Deep launcher once with prior company/product.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.workflow_launch_dto import WorkflowLaunchResult
from app.application.services.conversation_service import ConversationService
from app.application.services.follow_up_service import (
    FollowUpService,
    extract_prior_refs,
    merge_intent_for_upgrade,
    select_best_prior_analysis_intent,
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


def _empty_intent(raw: str) -> IntentUnderstandingResult:
    return IntentUnderstandingResult(
        type="competitive_analysis",
        company=None,
        competitors=[],
        product=None,
        objective=None,
        confidence=0.4,
        needs_clarification=True,
        raw_message=raw,
    )


def _analysis_started_msg(
    conversation_id: str,
    *,
    with_validated_input: bool = False,
) -> Message:
    intent = _intent(raw="对比飞猪和美团酒店，给出产品策略建议")
    meta: dict = {
        "message_type": "analysis_started",
        "workflow_type": "deep_analysis",
        "workflow_kind": "deep_analysis",
        "report_id": "prior-rep",
        "intent": intent.model_dump(),
    }
    if with_validated_input:
        meta["validated_input"] = {
            "our_company": "飞猪",
            "competitor_company": "美团",
            "competitors": ["美团"],
            "product": "酒店",
            "objective": "product_improvement",
            "scene": "产品策略建议",
            "raw_message": intent.raw_message,
        }
    return Message(
        id=new_id(),
        conversation_id=conversation_id,
        role="assistant",
        content="已收到分析请求：飞猪 的 酒店\n对比竞品：美团\n正在启动分析，请稍候…",
        task_id="prior-task",
        metadata=meta,
        created_at=utc_now(),
    )


def _follow_up_short_msg(conversation_id: str) -> Message:
    empty = _empty_intent("基于刚才结果，定价上有什么建议？")
    return Message(
        id=new_id(),
        conversation_id=conversation_id,
        role="assistant",
        content="- 建议保持价格带清晰（基于上轮）",
        task_id=None,
        metadata={
            "message_type": "follow_up_answered",
            "workflow_type": "follow_up",
            "follow_up_mode": "short_answer",
            "prior_task_id": "prior-task",
            "prior_report_id": "prior-rep",
            "intent": empty.model_dump(),
        },
        created_at=utc_now(),
    )


class TestSelectBestPriorAnalysisIntent:
    def test_ignores_empty_follow_up_intent(self) -> None:
        cid = "c-e2"
        msgs = [_analysis_started_msg(cid), _follow_up_short_msg(cid)]
        recovered = select_best_prior_analysis_intent(msgs)
        assert recovered is not None
        assert recovered["company"] == "飞猪"
        assert recovered["product"] == "酒店"
        assert recovered["competitors"] == ["美团"]

        refs = extract_prior_refs(msgs)
        assert refs["prior_task_id"] == "prior-task"
        assert refs["recovered_intent"]["company"] == "飞猪"

    def test_prefers_validated_input_snapshot(self) -> None:
        cid = "c-snap"
        msgs = [
            _analysis_started_msg(cid, with_validated_input=True),
            _follow_up_short_msg(cid),
        ]
        recovered = select_best_prior_analysis_intent(msgs)
        assert recovered is not None
        assert recovered["company"] == "飞猪"
        assert recovered["scene"] == "产品策略建议"

    def test_no_analysis_started_returns_none(self) -> None:
        cid = "c-empty"
        msgs = [_follow_up_short_msg(cid)]
        assert select_best_prior_analysis_intent(msgs) is None

    def test_merge_overlay_empty_keeps_base(self) -> None:
        base = select_best_prior_analysis_intent(
            [_analysis_started_msg("c1")],
        )
        assert base is not None
        merged = merge_intent_for_upgrade(base, _empty_intent("请基于刚才内容出一份完整竞品分析报告"))
        assert merged.company == "飞猪"
        assert merged.product == "酒店"
        assert merged.competitors == ["美团"]


@pytest.fixture
def conv_env(tmp_path: Path, monkeypatch):
    persistence = tmp_path / "persistence"
    persistence.mkdir()
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.stores.DATA_DIR",
        persistence,
    )
    # Isolate single-worker busy gate from any leftover on-disk pending tasks.
    from app.infrastructure.persistence import task_report_runtime

    monkeypatch.setattr(task_report_runtime, "_tasks", {})
    monkeypatch.setattr(task_report_runtime, "persist_tasks", lambda: None)

    project_store = ProjectStore()
    conversation_store = ConversationStore()
    message_store = MessageStore()
    project_service = ProjectService(store=project_store)
    intent_service = AsyncMock()
    deep = AsyncMock()
    deep.launch = AsyncMock(
        return_value=WorkflowLaunchResult(
            task_id="task-deep-upgrade",
            report_id="rep-deep-upgrade",
            status="pending",
        ),
    )
    deep._running = set()
    deep.has_in_process_tasks = MagicMock(return_value=False)
    collect = AsyncMock()
    collect.launch = AsyncMock(
        return_value=WorkflowLaunchResult(task_id="task-collect", report_id="rep-collect"),
    )
    collect._running = set()
    collect.has_in_process_tasks = MagicMock(return_value=False)
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


class TestFollowUpUpgradeE2:
    def test_e2_upgrade_after_empty_follow_up_intent(self, conv_env) -> None:
        """Step 7 DEF-E2: empty follow_up intent must not block Deep upgrade."""
        svc, project_service, intent_service, deep, collect, message_store = conv_env
        project = project_service.create_project("P-E2")
        conversation = svc.create_conversation(project.id)
        message_store.append_message(_analysis_started_msg(conversation.id))
        message_store.append_message(_follow_up_short_msg(conversation.id))

        raw = "请基于刚才内容出一份完整竞品分析报告"
        intent_service.understand = AsyncMock(return_value=_empty_intent(raw))
        result = asyncio.run(
            svc.process_user_message(conversation.id, raw, analysis_mode="full"),
        )

        assert result.status == "analysis_started"
        assert result.task_id == "task-deep-upgrade"
        deep.launch.assert_awaited_once()
        collect.launch.assert_not_awaited()
        meta = result.assistant_message.metadata or {}
        assert meta.get("follow_up_mode") == "upgrade_analysis"
        assert not meta.get("upgrade_error")
        assert meta.get("validated_input", {}).get("our_company") == "飞猪"

        req = deep.launch.await_args.args[0]
        assert req.our_company == "飞猪"
        assert req.product == "酒店"
        assert "美团" in req.competitor_company

    def test_upgrade_without_analysis_started_clarifies(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect, message_store = conv_env
        project = project_service.create_project("P-block")
        conversation = svc.create_conversation(project.id)
        # Only empty follow_up prior — has prior artifact signal via prior_task_id
        # but no recoverable deep entities. Seed a query_answered so has_prior is true.
        message_store.append_message(
            Message(
                id=new_id(),
                conversation_id=conversation.id,
                role="assistant",
                content="美团酒店最近有一些会员调整（短答）" * 3,
                task_id=None,
                metadata={
                    "message_type": "query_answered",
                    "workflow_type": "information_query",
                    "intent": _empty_intent("美团酒店最近有什么变化？").model_dump(),
                },
                created_at=utc_now(),
            ),
        )
        message_store.append_message(_follow_up_short_msg(conversation.id))

        raw = "请基于刚才内容出一份完整竞品分析报告"
        intent_service.understand = AsyncMock(return_value=_empty_intent(raw))
        result = asyncio.run(svc.process_user_message(conversation.id, raw))

        assert result.status == "follow_up_answered"
        assert result.task_id is None
        deep.launch.assert_not_awaited()
        meta = result.assistant_message.metadata or {}
        assert meta.get("follow_up_mode") == "upgrade_blocked_missing_entities"
        assert "公司" in result.assistant_message.content or "竞品" in result.assistant_message.content

    def test_short_follow_up_still_no_deep(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect, message_store = conv_env
        project = project_service.create_project("P-short")
        conversation = svc.create_conversation(project.id)
        message_store.append_message(_analysis_started_msg(conversation.id))
        raw = "基于刚才结果，定价上有什么建议？"
        intent_service.understand = AsyncMock(return_value=_empty_intent(raw))
        result = asyncio.run(svc.process_user_message(conversation.id, raw))
        assert result.status == "follow_up_answered"
        assert result.task_id is None
        deep.launch.assert_not_awaited()
        assert (result.assistant_message.metadata or {}).get("follow_up_mode") == "short_answer"

    def test_competitive_analysis_writes_validated_input(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect, _message_store = conv_env
        project = project_service.create_project("P-snap")
        conversation = svc.create_conversation(project.id)
        raw = "对比飞猪和美团酒店，给出产品策略建议"
        intent_service.understand = AsyncMock(return_value=_intent(raw=raw))
        result = asyncio.run(svc.process_user_message(conversation.id, raw, analysis_mode="fast"))
        assert result.status == "analysis_started"
        snap = (result.assistant_message.metadata or {}).get("validated_input") or {}
        assert snap.get("our_company") == "飞猪"
        assert snap.get("product") == "酒店"
        assert "美团" in (snap.get("competitor_company") or "")
