"""Research Task confirmation: no Deep/Collection launch until user confirms."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.research_task_dto import ConfirmResearchTaskRequest
from app.application.dto.workflow_launch_dto import WorkflowLaunchResult
from app.application.services.conversation_service import ConversationService
from app.application.services.project_service import ProjectService
from app.application.services.research_task_builder import (
    apply_confirmation_patch,
    build_research_task,
)
from app.application.services.router_service import RouterService
from app.application.dto.routing_dto import RoutingDecision
from app.infrastructure.persistence.copilot.stores import ConversationStore, MessageStore, ProjectStore


def _intent(**kwargs) -> IntentUnderstandingResult:
    base = dict(
        type="competitive_analysis",
        company="飞猪",
        competitors=["美团", "携程"],
        product="酒店",
        objective="分析飞猪酒店竞争力下降的原因",
        confidence=0.9,
        needs_clarification=False,
        raw_message="帮我分析飞猪酒店竞争力下降的原因。",
    )
    base.update(kwargs)
    return IntentUnderstandingResult(**base)  # type: ignore[arg-type]


@pytest.fixture
def env(tmp_path: Path, monkeypatch):
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
        return_value=WorkflowLaunchResult(task_id="task-deep", report_id="rep-deep", status="pending"),
    )
    deep.has_in_process_tasks = MagicMock(return_value=False)
    deep._running = set()
    collect = AsyncMock()
    collect.launch = AsyncMock(
        return_value=WorkflowLaunchResult(task_id="task-col", report_id="rep-col", status="pending"),
    )
    collect.has_in_process_tasks = MagicMock(return_value=False)
    collect._running = set()
    svc = ConversationService(
        conversation_store=conversation_store,
        message_store=message_store,
        project_service=project_service,
        intent_service=intent_service,
        workflow_launcher=deep,
        collection_launcher=collect,
        router_service=RouterService(),
    )
    return {
        "svc": svc,
        "project_service": project_service,
        "intent": intent_service,
        "deep": deep,
        "collect": collect,
    }


def test_builder_marks_inferred_competitors_and_default_scope():
    intent = _intent(competitors=["携程", "美团"], raw_message="帮我分析飞猪酒店竞争力下降的原因。")
    task = build_research_task(
        intent=intent,
        routing=RoutingDecision(
            workflow_type="competitive_analysis",
            legacy_workflow_kind="deep_analysis",
        ),
        conversation_id="c1",
        project_id="p1",
        source_message_id="m1",
    )
    assert task.analysis_subject.value == "飞猪"
    assert task.analysis_subject.source == "user_input"
    names = {item.value: item.source for item in task.competitors}
    assert names["携程"] == "system_inferred"
    assert names["美团"] == "system_inferred"
    assert task.research_scope.value == "近三年"
    assert task.research_scope.source == "system_default"
    assert task.analysis_product.value == "酒店"
    assert task.analysis_product.source == "user_input"


def test_builder_user_time_range_is_user_input():
    intent = _intent(raw_message="分析近一年飞猪 vs 美团酒店")
    intent.competitors = ["美团"]
    task = build_research_task(
        intent=intent,
        routing=None,
        conversation_id="c1",
        project_id="p1",
        source_message_id="m1",
    )
    assert task.research_scope.source == "user_input"
    assert "近一年" in (task.research_scope.value or "")


def test_patch_marks_edits_as_user_input():
    intent = _intent()
    task = build_research_task(
        intent=intent,
        routing=None,
        conversation_id="c1",
        project_id="p1",
        source_message_id="m1",
    )
    patched = apply_confirmation_patch(
        task,
        ConfirmResearchTaskRequest(competitors=["同程旅行"], analysis_goal="只看会员体系"),
    )
    assert patched.competitor_names() == ["同程旅行"]
    assert patched.competitors[0].source == "user_input"
    assert patched.analysis_goal.value == "只看会员体系"
    assert patched.analysis_goal.source == "user_input"


@pytest.mark.asyncio
async def test_complete_request_waits_for_confirmation(env) -> None:
    s = env
    project = s["project_service"].create_project("CA")
    conv = s["svc"].create_conversation(project.id)
    raw = "帮我分析飞猪酒店竞争力下降的原因，对比美团与携程"
    s["intent"].understand = AsyncMock(
        return_value=_intent(raw_message=raw, competitors=["美团", "携程"]),
    )
    result = await s["svc"].process_user_message(conv.id, raw)
    assert result.status == "awaiting_confirmation"
    assert result.task_id is None
    s["deep"].launch.assert_not_awaited()
    s["collect"].launch.assert_not_awaited()
    task = (result.assistant_message.metadata or {})["research_task"]
    assert task["status"] == "pending"
    assert task["analysis_subject"]["value"] == "飞猪"


@pytest.mark.asyncio
async def test_missing_fields_clarify_without_task(env) -> None:
    s = env
    project = s["project_service"].create_project("Gap")
    conv = s["svc"].create_conversation(project.id)
    raw = "帮我分析飞猪最近的发展情况。"
    s["intent"].understand = AsyncMock(
        return_value=_intent(
            company="飞猪",
            competitors=[],
            product=None,
            needs_clarification=True,
            missing_fields=["product", "competitors"],
            clarification_question="请告诉我要分析的具体产品或市场是什么？",
            raw_message=raw,
        ),
    )
    result = await s["svc"].process_user_message(conv.id, raw)
    assert result.status == "needs_clarification"
    s["deep"].launch.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_starts_deep_with_edited_competitors(env) -> None:
    s = env
    project = s["project_service"].create_project("Edit")
    conv = s["svc"].create_conversation(project.id)
    raw = "对比飞猪和美团酒店，给出产品策略建议"
    s["intent"].understand = AsyncMock(
        return_value=_intent(
            raw_message=raw,
            competitors=["美团"],
            objective="product_improvement",
        ),
    )
    pending = await s["svc"].process_user_message(conv.id, raw)
    task_id = pending.assistant_message.metadata["research_task"]["id"]
    confirmed = await s["svc"].confirm_research_task(
        conv.id,
        task_id,
        ConfirmResearchTaskRequest(competitors=["携程"], analysis_goal="只分析会员"),
    )
    assert confirmed.status == "analysis_started"
    s["deep"].launch.assert_awaited_once()
    s["collect"].launch.assert_not_awaited()
    req = s["deep"].launch.await_args.args[0]
    assert req.our_company == "飞猪"
    assert "携程" in req.competitor_company
    assert "美团" not in req.competitor_company
    assert (req.optional or {}).get("research_task_confirmed") is True
    assert "只分析会员" in (req.scene or "")


@pytest.mark.asyncio
async def test_duplicate_confirm_does_not_relaunch(env) -> None:
    s = env
    project = s["project_service"].create_project("Dup")
    conv = s["svc"].create_conversation(project.id)
    raw = "对比飞猪和美团酒店，给出产品策略建议"
    s["intent"].understand = AsyncMock(
        return_value=_intent(raw_message=raw, competitors=["美团"], objective="product_improvement"),
    )
    pending = await s["svc"].process_user_message(conv.id, raw)
    task_id = pending.assistant_message.metadata["research_task"]["id"]
    first = await s["svc"].confirm_research_task(conv.id, task_id)
    second = await s["svc"].confirm_research_task(conv.id, task_id)
    assert first.status == "analysis_started"
    assert second.status == "analysis_started"
    assert first.task_id == second.task_id == "task-deep"
    s["deep"].launch.assert_awaited_once()


@pytest.mark.asyncio
async def test_collection_waits_then_launches_collection_only(env) -> None:
    s = env
    project = s["project_service"].create_project("Col")
    conv = s["svc"].create_conversation(project.id)
    raw = "帮我收集字节跳动抖音产品近期信息"
    s["intent"].understand = AsyncMock(
        return_value=_intent(
            company="字节跳动",
            competitors=[],
            product="抖音",
            objective="intelligence_collection",
            raw_message=raw,
        ),
    )
    pending = await s["svc"].process_user_message(conv.id, raw)
    assert pending.status == "awaiting_confirmation"
    s["collect"].launch.assert_not_awaited()
    task_id = pending.assistant_message.metadata["research_task"]["id"]
    confirmed = await s["svc"].confirm_research_task(conv.id, task_id)
    assert confirmed.status == "analysis_started"
    s["collect"].launch.assert_awaited_once()
    s["deep"].launch.assert_not_awaited()
    req = s["collect"].launch.await_args.args[0]
    assert (req.optional or {}).get("workflow_kind") == "intelligence_collection"


@pytest.mark.asyncio
async def test_new_message_cancels_unconfirmed_task(env) -> None:
    s = env
    project = s["project_service"].create_project("New")
    conv = s["svc"].create_conversation(project.id)
    raw = "对比飞猪和美团酒店，给出产品策略建议"
    s["intent"].understand = AsyncMock(
        return_value=_intent(raw_message=raw, competitors=["美团"], objective="product_improvement"),
    )
    pending = await s["svc"].process_user_message(conv.id, raw)
    old_id = pending.assistant_message.metadata["research_task"]["id"]
    s["intent"].understand = AsyncMock(
        return_value=_intent(
            company="滴滴出行",
            competitors=["如祺出行"],
            product="出行",
            objective="product_improvement",
            raw_message="帮我完成滴滴出行和如祺出行的竞品分析报告",
        ),
    )
    again = await s["svc"].process_user_message(
        conv.id, "帮我完成滴滴出行和如祺出行的竞品分析报告",
    )
    assert again.status == "awaiting_confirmation"
    new_id = again.assistant_message.metadata["research_task"]["id"]
    assert new_id != old_id
    s["deep"].launch.assert_not_awaited()
    conv_obj = s["svc"].get_conversation(conv.id)
    pending_meta = (conv_obj.metadata or {}).get("pending_research_task") or {}
    assert pending_meta.get("id") == new_id
