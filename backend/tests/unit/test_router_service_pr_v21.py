"""Phase 2 V2.1: RouterService + LegacyBridge + out_of_scope."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.workflow_launch_dto import WorkflowLaunchResult
from app.application.services.conversation_service import ConversationService
from app.application.services.project_service import ProjectService
from app.application.services.router_service import RouterService
from app.infrastructure.persistence.copilot.stores import ConversationStore, MessageStore, ProjectStore


def _intent(
    *,
    type_: str = "competitive_analysis",
    company: str | None = "龙腾出行",
    competitors: list[str] | None = None,
    product: str | None = "机场场景",
    objective: str | None = "product_improvement",
    raw: str = "",
    confidence: float = 0.9,
    needs_clarification: bool = False,
) -> IntentUnderstandingResult:
    return IntentUnderstandingResult(
        type=type_,  # type: ignore[arg-type]
        company=company,
        competitors=competitors or [],
        product=product,
        objective=objective,
        confidence=confidence,
        needs_clarification=needs_clarification,
        clarification_question="请补充" if needs_clarification else None,
        raw_message=raw,
    )


class TestRouterService:
    def setup_method(self) -> None:
        self.router = RouterService()

    def test_unsupported_to_out_of_scope(self) -> None:
        d = self.router.route(
            _intent(type_="unsupported", company=None, product=None, raw="今天天气怎么样"),
            "今天天气怎么样",
        )
        assert d.workflow_type == "out_of_scope"
        assert d.legacy_workflow_kind is None

    def test_longteng_report_competitive_analysis(self) -> None:
        raw = (
            "帮我完成龙腾出行和悦途的机场场景的竞品分析报告，"
            "重点是商业行为、海外战略方向的竞品差异"
        )
        d = self.router.route(
            _intent(competitors=["悦途"], raw=raw),
            raw,
        )
        assert d.workflow_type == "competitive_analysis"
        assert d.legacy_workflow_kind == "deep_analysis"

    def test_collect_to_research(self) -> None:
        raw = "帮我收集字节跳动抖音产品近期信息"
        d = self.router.route(
            _intent(
                company="字节跳动",
                competitors=[],
                product="抖音",
                objective="intelligence_collection",
                raw=raw,
            ),
            raw,
        )
        assert d.workflow_type == "research"
        assert d.legacy_workflow_kind == "intelligence_collection"

    def test_light_query_information_query(self) -> None:
        raw = "美团酒店最近有什么变化"
        d = self.router.route(
            _intent(company="美团", competitors=[], product="酒店", raw=raw),
            raw,
        )
        assert d.workflow_type == "information_query"
        assert d.legacy_workflow_kind is None

    def test_compare_report_still_competitive(self) -> None:
        raw = "对比美团和飞猪最近变化并出报告"
        d = self.router.route(
            _intent(company="美团", competitors=["飞猪"], product="酒店", raw=raw),
            raw,
        )
        assert d.workflow_type == "competitive_analysis"
        assert d.legacy_workflow_kind == "deep_analysis"

    def test_collect_recent_still_research(self) -> None:
        raw = "收集美团酒店最近资料"
        d = self.router.route(
            _intent(
                company="美团",
                competitors=[],
                product="酒店",
                objective="intelligence_collection",
                raw=raw,
            ),
            raw,
        )
        assert d.workflow_type == "research"
        assert d.legacy_workflow_kind == "intelligence_collection"

    def test_light_query_even_if_intent_unsupported(self) -> None:
        raw = "美团最近有什么变化"
        d = self.router.route(
            _intent(type_="unsupported", company=None, product=None, competitors=[], raw=raw),
            raw,
        )
        assert d.workflow_type == "information_query"

    def test_legacy_bridge_matches_resolve_workflow_kind(self) -> None:
        from app.application.services.intent_mapper import resolve_workflow_kind

        cases = [
            (
                "帮我完成龙腾出行和悦途的机场场景的竞品分析报告，重点是商业行为",
                ["悦途"],
                "product_improvement",
            ),
            (
                "帮我收集字节跳动抖音产品近期信息",
                [],
                "intelligence_collection",
            ),
        ]
        for raw, comps, obj in cases:
            intent = _intent(competitors=comps, objective=obj, raw=raw, product="x")
            kind = resolve_workflow_kind(intent, raw)
            d = self.router.route(intent, raw)
            if kind == "deep_analysis":
                assert d.workflow_type == "competitive_analysis"
                assert d.legacy_workflow_kind == "deep_analysis"
            else:
                assert d.workflow_type == "research"
                assert d.legacy_workflow_kind == "intelligence_collection"


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
        return_value=WorkflowLaunchResult(
            task_id="task-deep",
            status="pending",
            report_id="rep-deep",
        ),
    )
    collect = AsyncMock()
    collect.launch = AsyncMock(
        return_value=WorkflowLaunchResult(
            task_id="task-collect",
            status="pending",
            report_id="rep-collect",
        ),
    )
    svc = ConversationService(
        conversation_store=conversation_store,
        message_store=message_store,
        project_service=project_service,
        intent_service=intent_service,
        workflow_launcher=deep,
        collection_launcher=collect,
        router_service=RouterService(),
    )
    return svc, project_service, intent_service, deep, collect


class TestConversationRouterDispatch:
    def test_competitive_analysis_calls_deep_only(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        raw = (
            "帮我完成龙腾出行和悦途的机场场景的竞品分析报告，"
            "重点是商业行为、海外战略方向的竞品差异"
        )
        intent_service.understand = AsyncMock(
            return_value=_intent(competitors=["悦途"], raw=raw),
        )
        result = asyncio.run(svc.process_user_message(conversation.id, raw, analysis_mode="full"))
        assert result.status == "analysis_started"
        assert result.task_id == "task-deep"
        assert result.routing_decision is not None
        assert result.routing_decision.workflow_type == "competitive_analysis"
        deep.launch.assert_awaited_once()
        collect.launch.assert_not_awaited()
        meta = result.assistant_message.metadata or {}
        assert meta["workflow_type"] == "deep_analysis"
        assert meta["workflow_kind"] == "deep_analysis"
        assert meta["routing_decision"]["workflow_type"] == "competitive_analysis"

    def test_research_calls_collection_only(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        raw = "帮我收集字节跳动抖音产品近期信息"
        intent_service.understand = AsyncMock(
            return_value=_intent(
                company="字节跳动",
                competitors=[],
                product="抖音",
                objective="intelligence_collection",
                raw=raw,
            ),
        )
        result = asyncio.run(svc.process_user_message(conversation.id, raw))
        assert result.status == "analysis_started"
        assert result.task_id == "task-collect"
        assert result.routing_decision.workflow_type == "research"
        collect.launch.assert_awaited_once()
        deep.launch.assert_not_awaited()
        meta = result.assistant_message.metadata or {}
        assert meta["workflow_type"] == "intelligence_collection"
        assert meta["routing_decision"]["workflow_type"] == "research"

    def test_weather_out_of_scope_no_launcher(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        raw = "今天天气怎么样"
        intent_service.understand = AsyncMock(
            return_value=_intent(
                type_="unsupported",
                company=None,
                product=None,
                competitors=[],
                raw=raw,
            ),
        )
        result = asyncio.run(svc.process_user_message(conversation.id, raw))
        assert result.status == "out_of_scope"
        assert result.task_id is None
        assert result.routing_decision.workflow_type == "out_of_scope"
        deep.launch.assert_not_awaited()
        collect.launch.assert_not_awaited()
        assert "超出" in result.assistant_message.content or "服务范围" in result.assistant_message.content

    def test_light_query_answers_without_launcher(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        raw = "美团酒店最近有什么变化"
        intent_service.understand = AsyncMock(
            return_value=_intent(company="美团", competitors=[], product="酒店", raw=raw),
        )

        async def fake_answer(**kwargs):
            from app.application.services.simple_query_service import (
                QuerySource,
                SimpleQueryResult,
            )
            return SimpleQueryResult(
                answer_markdown="- 有会员调整\n\n- [来源](https://ex.com/1)",
                sources=[QuerySource(title="来源", url="https://ex.com/1", snippet="x")],
                confidence=0.7,
                metadata={"query_mode": "information_query", "hit_count": 1},
            )

        svc._simple_query.answer = fake_answer  # type: ignore[method-assign]
        result = asyncio.run(svc.process_user_message(conversation.id, raw, analysis_mode="full"))
        assert result.status == "query_answered"
        assert result.task_id is None
        assert result.routing_decision.workflow_type == "information_query"
        assert "会员" in result.assistant_message.content
        deep.launch.assert_not_awaited()
        collect.launch.assert_not_awaited()
        meta = result.assistant_message.metadata or {}
        assert meta["workflow_type"] == "information_query"
        assert meta["message_type"] == "query_answered"
        assert meta.get("query_sources")

    def test_clarification_skips_launchers(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        intent_service.understand = AsyncMock(
            return_value=_intent(needs_clarification=True, raw="测试"),
        )
        result = asyncio.run(svc.process_user_message(conversation.id, "测试"))
        assert result.status == "needs_clarification"
        assert result.routing_decision is None
        deep.launch.assert_not_awaited()
        collect.launch.assert_not_awaited()

    def test_light_query_bypasses_competitor_clarification(self, conv_env) -> None:
        svc, project_service, intent_service, deep, collect = conv_env
        project = project_service.create_project("P1")
        conversation = svc.create_conversation(project.id)
        raw = "美团酒店最近有什么变化"
        intent_service.understand = AsyncMock(
            return_value=_intent(
                company="美团",
                competitors=[],
                product="酒店",
                raw=raw,
                needs_clarification=True,
            ),
        )

        async def fake_answer(**kwargs):
            from app.application.services.simple_query_service import SimpleQueryResult
            return SimpleQueryResult(
                answer_markdown="摘要",
                sources=[],
                confidence=0.5,
                metadata={"query_mode": "information_query"},
            )

        svc._simple_query.answer = fake_answer  # type: ignore[method-assign]
        result = asyncio.run(svc.process_user_message(conversation.id, raw))
        assert result.status == "query_answered"
        assert result.routing_decision.workflow_type == "information_query"
        deep.launch.assert_not_awaited()
        collect.launch.assert_not_awaited()
