"""Evidence Reuse V1 Step 2B — Gap Search (narrowed Research + merge)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import EvidenceItemDTO, ResearchInput
from app.infrastructure.agents.base import AgentContext
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.persistence import task_report_runtime
from app.infrastructure.tools.dimension_router import SourceExecutionPlan
from app.infrastructure.tools.research_source import SourceResult


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
    research_tasks: list[dict] | None = None,
) -> ResearchInput:
    comps = competitors if competitors is not None else ["如祺出行"]
    tasks = research_tasks if research_tasks is not None else [
        {
            "task_id": "task_web_000",
            "source_type": "web",
            "keywords": ["滴滴出行 产品定位与品牌", "如祺出行 用户画像与行为变化", "增长策略"],
            "priority": 3,
            "dependencies": [],
        },
        {
            "task_id": "task_web_001",
            "source_type": "web",
            "keywords": ["滴滴出行 增长策略与市场", "如祺出行 增长策略与市场"],
            "priority": 3,
            "dependencies": [],
        },
    ]
    return ResearchInput(
        research_plan={
            "objective": "竞品分析",
            "analysis_scope": scope
            or ["产品定位与品牌", "用户画像与行为变化", "增长策略与市场"],
            "research_tasks": tasks,
        },
        our_company=our,
        competitor_company=competitor_company,
        product="出行",
        project_id=project_id,
        workflow_kind=workflow_kind,
        competitors=comps,
        evidence_max_age_months=48,
    )


def _fake_sel_plan(dimensions: list[str], keywords: list[str] | None = None):
    plan = MagicMock()
    plan.dimensions = list(dimensions)
    plan.objective = "gap"
    plan.all_source_types = ["web"]
    t = MagicMock()
    t.dimension = dimensions[0] if dimensions else "web"
    t.sources = ["web"]
    t.keywords = list(keywords or dimensions)
    plan.tasks = [t]
    return plan


def _source_hit(url: str, title: str, content: str) -> SourceResult:
    item = MagicMock()
    item.url = url
    item.title = title
    item.content = content
    item.snippet = content
    item.published_date = "2025-06-01"
    return SourceResult(
        items=[item],
        source_type="web",
        source_name="mock",
        status="success",
        error=None,
        total_found=1,
        duration_ms=1,
    )


@pytest.fixture
def agent() -> ResearchAgent:
    return ResearchAgent()


@pytest.mark.asyncio
async def test_2b_missing_dimension_narrows_route(
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
                url="https://ex.com/pos",
                title="滴滴出行 定位",
                content="滴滴出行品牌",
                category="positioning",
                eid="E017",
            ),
            _item(
                url="https://ex.com/users",
                title="如祺出行 用户",
                content="如祺出行用户画像",
                category="users",
                eid="E023",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    captured: dict = {}

    async def _route(**kwargs):
        captured["dimensions"] = list(kwargs.get("dimensions") or [])
        captured["keywords"] = list(kwargs.get("keywords") or [])
        return _fake_sel_plan(captured["dimensions"], captured["keywords"])

    execute = AsyncMock(
        return_value=[
            _source_hit(
                "https://ex.com/growth",
                "如祺出行 增长",
                "如祺出行增长策略与市场",
            ),
        ],
    )

    async def _extract(_obj, _results, _inp, _max, _tl, task_id=""):
        return (
            [
                EvidenceItemDTO(
                    id="E099",
                    title="如祺出行 增长",
                    source="mock",
                    url="https://ex.com/growth",
                    date="2025-06-01",
                    content="如祺出行增长策略与市场",
                    category="growth",
                ),
            ],
            "ok",
        )

    with (
        patch("app.infrastructure.agents.research_agent.llm_router.route", AsyncMock(side_effect=_route)),
        patch("app.infrastructure.agents.research_agent.source_router.execute_plan", execute),
        patch.object(agent, "_extract_evidence_from_sources", AsyncMock(side_effect=_extract)),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(_ctx(), _input())

    assert result.success
    assert result.phase_record.get("gap_search") is True
    assert captured["dimensions"] == ["增长策略与市场"]
    assert any("增长" in k for k in captured["keywords"])
    # historical retained
    urls = {e.url for e in result.output.evidence_bundle.evidence_items}
    assert "https://ex.com/pos" in urls
    assert "https://ex.com/users" in urls
    assert "https://ex.com/growth" in urls
    # narrowed vs full scope (3 dims → 1)
    assert len(captured["dimensions"]) < 3
    execute.assert_awaited()
    plan_arg = execute.await_args.args[0]
    assert isinstance(plan_arg, SourceExecutionPlan)
    assert plan_arg.dimensions == ["增长策略与市场"]


@pytest.mark.asyncio
async def test_2b_missing_entity_focuses_keywords(
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
                url="https://ex.com/d1",
                title="滴滴出行 定位",
                content="仅滴滴出行",
                category="positioning",
            ),
            _item(
                url="https://ex.com/d2",
                title="滴滴出行 用户",
                content="仅滴滴出行用户",
                category="users",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    captured: dict = {}

    async def _route(**kwargs):
        captured["keywords"] = list(kwargs.get("keywords") or [])
        captured["dimensions"] = list(kwargs.get("dimensions") or [])
        return _fake_sel_plan(captured["dimensions"] or ["产品定位与品牌"], captured["keywords"])

    execute = AsyncMock(
        return_value=[
            _source_hit("https://ex.com/ruqi", "如祺出行", "如祺出行定位与用户"),
        ],
    )

    async def _extract(_obj, _results, _inp, _max, _tl, task_id=""):
        return (
            [
                EvidenceItemDTO(
                    id="N1",
                    title="如祺出行",
                    source="mock",
                    url="https://ex.com/ruqi",
                    date="2025-06-01",
                    content="如祺出行定位与用户",
                    category="positioning",
                ),
            ],
            "ok",
        )

    with (
        patch("app.infrastructure.agents.research_agent.llm_router.route", AsyncMock(side_effect=_route)),
        patch("app.infrastructure.agents.research_agent.source_router.execute_plan", execute),
        patch.object(agent, "_extract_evidence_from_sources", AsyncMock(side_effect=_extract)),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(
            _ctx(),
            _input(scope=["产品定位与品牌", "用户画像与行为变化"]),
        )

    assert result.phase_record.get("gap_search") is True
    assert any("如祺" in k for k in captured["keywords"])
    # Should not be a generic full-pair keyword-only plan without Ruqi focus
    assert result.phase_record["reuse_meta"]["gap_entities"]
    assert any("如祺" in e for e in result.phase_record["reuse_meta"]["gap_entities"])


@pytest.mark.asyncio
async def test_2b_entity_and_dimension_gap(
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
                url="https://ex.com/d1",
                title="滴滴出行 定位",
                content="滴滴出行",
                category="positioning",
            ),
            _item(
                url="https://ex.com/d2",
                title="滴滴出行 用户",
                content="滴滴出行",
                category="users",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    captured: dict = {}

    async def _route(**kwargs):
        captured["dimensions"] = list(kwargs.get("dimensions") or [])
        captured["keywords"] = list(kwargs.get("keywords") or [])
        return _fake_sel_plan(captured["dimensions"], captured["keywords"])

    with (
        patch("app.infrastructure.agents.research_agent.llm_router.route", AsyncMock(side_effect=_route)),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
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
        await agent.arun(_ctx(), _input())

    assert captured["dimensions"] == ["增长策略与市场"]
    assert any("如祺" in k and "增长" in k for k in captured["keywords"])


@pytest.mark.asyncio
async def test_2b_merge_historical_and_new(
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
                url="https://ex.com/pos",
                title="滴滴出行",
                content="滴滴出行",
                category="positioning",
            ),
            _item(
                url="https://ex.com/users",
                title="如祺出行",
                content="如祺出行用户",
                category="users",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    async def _extract(_obj, _results, _inp, _max, _tl, task_id=""):
        return (
            [
                EvidenceItemDTO(
                    id="N1",
                    title="增长",
                    source="mock",
                    url="https://ex.com/new",
                    date="2025-06-01",
                    content="如祺出行增长",
                    category="growth",
                ),
            ],
            "ok",
        )

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(return_value=_fake_sel_plan(["增长策略与市场"])),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            AsyncMock(return_value=[]),
        ),
        patch.object(agent, "_extract_evidence_from_sources", AsyncMock(side_effect=_extract)),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(_ctx(), _input())

    urls = [e.url for e in result.output.evidence_bundle.evidence_items]
    assert "https://ex.com/pos" in urls
    assert "https://ex.com/users" in urls
    assert "https://ex.com/new" in urls
    assert len(urls) == 3


@pytest.mark.asyncio
async def test_2b_url_dedupe_across_seed_and_new(
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
                url="https://ex.com/same",
                title="滴滴出行",
                content="滴滴出行定位",
                category="positioning",
            ),
            _item(
                url="https://ex.com/users",
                title="如祺出行",
                content="如祺出行用户",
                category="users",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    async def _extract(_obj, _results, _inp, _max, _tl, task_id=""):
        return (
            [
                EvidenceItemDTO(
                    id="N1",
                    title="dup",
                    source="mock",
                    url="https://ex.com/same",
                    date="2025-06-01",
                    content="重复 URL 增长",
                    category="growth",
                ),
                EvidenceItemDTO(
                    id="N2",
                    title="new growth",
                    source="mock",
                    url="https://ex.com/growth",
                    date="2025-06-01",
                    content="如祺出行增长",
                    category="growth",
                ),
            ],
            "ok",
        )

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(return_value=_fake_sel_plan(["增长策略与市场"])),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            AsyncMock(return_value=[]),
        ),
        patch.object(agent, "_extract_evidence_from_sources", AsyncMock(side_effect=_extract)),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(_ctx(), _input())

    urls = [e.url for e in result.output.evidence_bundle.evidence_items]
    assert urls.count("https://ex.com/same") == 1


@pytest.mark.asyncio
async def test_2b_renumber_after_merge(
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
                eid="E017",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行",
                content="如祺出行",
                category="users",
                eid="E031",
            ),
        ],
    )
    monkeypatch.setattr(task_report_runtime, "_tasks", {"hist-1": hist})

    async def _extract(_obj, _results, _inp, _max, _tl, task_id=""):
        return (
            [
                EvidenceItemDTO(
                    id="E099",
                    title="g",
                    source="mock",
                    url="https://ex.com/c",
                    date="2025-06-01",
                    content="如祺出行增长",
                    category="growth",
                ),
            ],
            "ok",
        )

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(return_value=_fake_sel_plan(["增长策略与市场"])),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            AsyncMock(return_value=[]),
        ),
        patch.object(agent, "_extract_evidence_from_sources", AsyncMock(side_effect=_extract)),
        patch.object(
            agent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(_ctx(), _input())

    ids = [e.id for e in result.output.evidence_bundle.evidence_items]
    assert ids == [f"E{i:03d}" for i in range(1, len(ids) + 1)]
    assert "E017" not in ids and "E031" not in ids and "E099" not in ids


@pytest.mark.asyncio
async def test_2b_different_competitors_full_research(
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

    route_dims: list = []

    async def _route(**kwargs):
        route_dims.extend(kwargs.get("dimensions") or [])
        return _fake_sel_plan(list(kwargs.get("dimensions") or ["产品定位与品牌"]))

    with (
        patch("app.infrastructure.agents.research_agent.llm_router.route", AsyncMock(side_effect=_route)),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
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

    assert result.phase_record.get("gap_search") is not True
    # Full scope (3 dims), not narrowed to a single gap dim
    assert len(route_dims) >= 2


@pytest.mark.asyncio
async def test_2b_collection_full_research(
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

    with (
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(return_value=_fake_sel_plan(["产品定位与品牌", "用户画像与行为变化", "增长策略与市场"])),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
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

    assert result.phase_record.get("gap_search") is not True
    assert result.phase_record.get("skipped_search") is not True


@pytest.mark.asyncio
async def test_2b_no_history_full_research(
    agent: ResearchAgent,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(task_report_runtime, "_tasks", {})
    route_calls = {"n": 0}

    async def _route(**kwargs):
        route_calls["n"] += 1
        return _fake_sel_plan(list(kwargs.get("dimensions") or ["产品定位与品牌"]))

    with (
        patch("app.infrastructure.agents.research_agent.llm_router.route", AsyncMock(side_effect=_route)),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
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

    assert route_calls["n"] == 1
    assert result.phase_record.get("gap_search") is not True
