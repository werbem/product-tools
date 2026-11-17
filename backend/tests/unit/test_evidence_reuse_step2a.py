"""Evidence Reuse V1 Step 2A — Zero Search Reuse via ResearchAgent."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import ResearchInput
from app.infrastructure.agents.base import AgentContext
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.persistence import task_report_runtime


def _item(
    *,
    url: str,
    title: str,
    content: str,
    category: str,
    date_str: str = "2025-06-01",
    eid: str = "E099",
) -> dict:
    return {
        "id": eid,
        "title": title,
        "source": "Tavily",
        "source_type": "web",
        "url": url,
        "date": date_str,
        "content": content,
        "confidence": "medium",
        "category": category,
        "extracted_at": "2026-09-01T00:00:00",
    }


def _hist_task(
    task_id: str,
    *,
    project_id: str,
    our: str,
    competitors: list[str],
    items: list[dict],
    workflow_kind: str = "deep_analysis",
) -> dict:
    return {
        "task_id": task_id,
        "status": "completed",
        "project_id": project_id,
        "workflow_kind": (
            "intelligence_collection"
            if workflow_kind == "intelligence_collection"
            else None
        ),
        "state": {
            "user_input": {
                "our_company": our,
                "competitor_company": "、".join(competitors),
                "optional": {
                    "competitors": competitors,
                    "workflow_kind": workflow_kind,
                },
            },
            "validated_input": {
                "our_company": our,
                "competitor_company": "、".join(competitors),
            },
            "evidence_bundle": {"evidence_items": items},
            "research_plan": {
                "analysis_scope": ["产品定位与品牌", "用户画像与行为变化"],
            },
        },
    }


def _ctx(task_id: str = "current-task") -> AgentContext:
    return AgentContext(task_id=task_id, current_phase="researching")


def _input(
    *,
    project_id: str | None = "p1",
    workflow_kind: str | None = "deep_analysis",
    our: str = "滴滴出行",
    competitors: list[str] | None = None,
    competitor_company: str = "如祺出行",
    scope: list[str] | None = None,
) -> ResearchInput:
    comps = competitors if competitors is not None else ["如祺出行"]
    return ResearchInput(
        research_plan={
            "objective": "竞品分析",
            "analysis_scope": scope
            or ["产品定位与品牌", "用户画像与行为变化"],
            "research_tasks": [],
        },
        our_company=our,
        competitor_company=competitor_company,
        product="出行",
        project_id=project_id,
        workflow_kind=workflow_kind,
        competitors=comps,
        evidence_max_age_months=48,
    )


@pytest.fixture
def agent() -> ResearchAgent:
    return ResearchAgent()


@pytest.mark.asyncio
async def test_2a_sufficient_skips_search_and_extraction(
    agent: ResearchAgent,
    monkeypatch: pytest.MonkeyPatch,
):
    hist = _hist_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行 定位",
                content="滴滴出行品牌定位",
                category="positioning",
                eid="E017",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行 用户",
                content="如祺出行用户画像",
                category="users",
                eid="E023",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    route = AsyncMock(side_effect=AssertionError("llm_router.route must not run"))
    execute = AsyncMock(side_effect=AssertionError("execute_plan must not run"))
    extract = AsyncMock(side_effect=AssertionError("extraction must not run"))

    with (
        patch("app.infrastructure.agents.research_agent.llm_router.route", route),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            execute,
        ),
        patch.object(agent, "_extract_evidence_from_sources", extract),
    ):
        result = await agent.arun(_ctx(), _input())

    assert result.success
    assert result.phase_record.get("skipped_search") is True
    assert result.phase_record.get("sources_called") == 0
    assert result.phase_record["reuse_meta"]["sufficient"] is True
    assert result.phase_record["reuse_meta"]["skipped_search"] is True
    assert result.phase_record["reuse_meta"]["reused_count"] > 0

    bundle = result.output.evidence_bundle
    quality = result.output.quality_report
    assert bundle is not None
    assert len(bundle.evidence_items) >= 2
    assert quality is not None
    assert quality.sources_attempted == 0
    assert quality.sources_succeeded == 0
    route.assert_not_awaited()
    execute.assert_not_awaited()
    extract.assert_not_awaited()


@pytest.mark.asyncio
async def test_2a_different_competitors_falls_through_to_search(
    agent: ResearchAgent,
    monkeypatch: pytest.MonkeyPatch,
):
    hist = _hist_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行",
                content="滴滴出行",
                category="positioning",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行",
                content="如祺出行",
                category="users",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    route_calls = {"n": 0}

    async def _route(**_kwargs):
        route_calls["n"] += 1
        raise RuntimeError("force rule fallback")

    empty_plan = MagicMock()
    empty_plan.dimensions = ["产品定位与品牌"]
    empty_plan.tasks = []
    empty_plan.all_source_types = ["web"]

    execute = AsyncMock(return_value=[])

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(side_effect=_route),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_selection.build_plan",
            return_value=empty_plan,
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            execute,
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.search_many",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            agent,
            "_extract_evidence_from_sources",
            AsyncMock(return_value=([], "none")),
        ),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(
            _ctx(),
            _input(competitors=["高德打车"], competitor_company="高德打车"),
        )

    assert result.success
    assert result.phase_record.get("skipped_search") is not True
    assert route_calls["n"] == 1
    execute.assert_awaited()


@pytest.mark.asyncio
async def test_2a_collection_does_not_shortcut(
    agent: ResearchAgent,
    monkeypatch: pytest.MonkeyPatch,
):
    hist = _hist_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行",
                content="滴滴出行定位",
                category="positioning",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行",
                content="如祺出行用户",
                category="users",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    route_calls = {"n": 0}

    async def _route(**_kwargs):
        route_calls["n"] += 1
        raise RuntimeError("force fallback")

    empty_plan = MagicMock()
    empty_plan.dimensions = ["产品定位与品牌"]
    empty_plan.tasks = []
    empty_plan.all_source_types = ["web"]
    execute = AsyncMock(return_value=[])

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(side_effect=_route),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_selection.build_plan",
            return_value=empty_plan,
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            execute,
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.search_many",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            agent,
            "_extract_evidence_from_sources",
            AsyncMock(return_value=([], "none")),
        ),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(
            _ctx(),
            _input(workflow_kind="intelligence_collection"),
        )

    assert result.success
    assert result.phase_record.get("skipped_search") is not True
    assert route_calls["n"] == 1
    execute.assert_awaited()


@pytest.mark.asyncio
async def test_2a_renumbers_evidence_ids(
    agent: ResearchAgent,
    monkeypatch: pytest.MonkeyPatch,
):
    hist = _hist_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行",
                content="滴滴出行定位",
                category="positioning",
                eid="E017",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行",
                content="如祺出行用户",
                category="users",
                eid="E023",
            ),
            _item(
                url="https://ex.com/c",
                title="滴滴出行 补充",
                content="滴滴出行与如祺出行",
                category="positioning",
                eid="E031",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(side_effect=AssertionError("no route")),
        ),
    ):
        result = await agent.arun(_ctx(), _input())

    ids = [e.id for e in result.output.evidence_bundle.evidence_items]
    assert ids == [f"E{i:03d}" for i in range(1, len(ids) + 1)]
    assert "E017" not in ids
    assert "E023" not in ids
    assert "E031" not in ids
    # sources_used aligned to current E00x
    src_ids = [s.get("source_id") for s in result.output.evidence_bundle.sources_used]
    assert src_ids == ids


@pytest.mark.asyncio
async def test_2a_first_research_without_history_keeps_search(
    agent: ResearchAgent,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(task_report_runtime, "_tasks", {})

    route_calls = {"n": 0}

    async def _route(**_kwargs):
        route_calls["n"] += 1
        raise RuntimeError("force fallback")

    empty_plan = MagicMock()
    empty_plan.dimensions = ["产品定位与品牌"]
    empty_plan.tasks = []
    empty_plan.all_source_types = ["web"]
    execute = AsyncMock(return_value=[])

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(side_effect=_route),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_selection.build_plan",
            return_value=empty_plan,
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            execute,
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.search_many",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            agent,
            "_extract_evidence_from_sources",
            AsyncMock(return_value=([], "none")),
        ),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(_ctx(), _input())

    assert result.success
    assert result.phase_record.get("skipped_search") is not True
    assert route_calls["n"] == 1
    execute.assert_awaited()


@pytest.mark.asyncio
async def test_2a_no_project_id_skips_reuse_path(
    agent: ResearchAgent,
    monkeypatch: pytest.MonkeyPatch,
):
    """Missing project_id → reuse not attempted; existing Research runs."""
    hist = _hist_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行",
                content="滴滴出行",
                category="positioning",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行",
                content="如祺出行",
                category="users",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    route_calls = {"n": 0}

    async def _route(**_kwargs):
        route_calls["n"] += 1
        raise RuntimeError("force fallback")

    empty_plan = MagicMock()
    empty_plan.dimensions = ["产品定位与品牌"]
    empty_plan.tasks = []
    empty_plan.all_source_types = ["web"]
    execute = AsyncMock(return_value=[])

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(side_effect=_route),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_selection.build_plan",
            return_value=empty_plan,
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            execute,
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.search_many",
            AsyncMock(return_value=[]),
        ),
        patch.object(
            agent,
            "_extract_evidence_from_sources",
            AsyncMock(return_value=([], "none")),
        ),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(_ctx(), _input(project_id=None))

    assert result.phase_record.get("skipped_search") is not True
    assert route_calls["n"] == 1
    execute.assert_awaited()
