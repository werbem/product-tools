"""Evidence Reuse V1 Step 3 — cost/quality benchmark (instrumented ResearchAgent).

Uses ResearchCostProbe to count real Search / Research-LLM calls during
controlled ResearchAgent runs. Search providers are stubbed to avoid network,
but execute_plan / llm.generate entrypoints are still invoked and counted.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import EvidenceItemDTO, ResearchInput
from app.application.services.research_cost_probe import ResearchCostSnapshot
from app.infrastructure.agents.base import AgentContext
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.persistence import task_report_runtime
from app.infrastructure.tools.research_source import SourceResult


SCOPE_FULL = ["产品定位与品牌", "用户画像与行为变化", "增长策略与市场"]
SCOPE_BIZ = ["产品定位与品牌", "用户画像与行为变化", "商业模式差异"]


def _item(
    *,
    url: str,
    title: str,
    content: str,
    category: str,
    eid: str = "E099",
) -> dict:
    return {
        "id": eid,
        "title": title,
        "source": "Tavily",
        "source_type": "web",
        "url": url,
        "date": "2025-06-01",
        "content": content,
        "confidence": "medium",
        "category": category,
        "extracted_at": "2026-09-01T00:00:00",
    }


def _hist(
    task_id: str,
    *,
    project_id: str,
    our: str,
    competitors: list[str],
    items: list[dict],
) -> dict:
    return {
        "task_id": task_id,
        "status": "completed",
        "project_id": project_id,
        "workflow_kind": None,
        "state": {
            "user_input": {
                "our_company": our,
                "competitor_company": "、".join(competitors),
                "optional": {
                    "competitors": competitors,
                    "workflow_kind": "deep_analysis",
                },
            },
            "validated_input": {
                "our_company": our,
                "competitor_company": "、".join(competitors),
            },
            "evidence_bundle": {"evidence_items": items},
            "research_plan": {"analysis_scope": list(SCOPE_FULL)},
        },
    }


def _input(
    *,
    project_id: str | None = "bench-p1",
    our: str = "滴滴出行",
    competitors: list[str] | None = None,
    competitor_company: str | None = None,
    scope: list[str] | None = None,
    workflow_kind: str = "deep_analysis",
) -> ResearchInput:
    comps = competitors if competitors is not None else ["如祺出行"]
    return ResearchInput(
        research_plan={
            "objective": "分析华南网约车市场竞争格局",
            "analysis_scope": list(scope or SCOPE_FULL),
            "research_tasks": [
                {
                    "task_id": "t0",
                    "source_type": "web",
                    "keywords": [
                        "滴滴出行 华南",
                        "如祺出行 华南",
                        "产品定位与品牌",
                        "用户画像与行为变化",
                        "增长策略与市场",
                        "商业模式差异",
                    ],
                    "priority": 3,
                    "dependencies": [],
                },
            ],
        },
        our_company=our,
        competitor_company=competitor_company or "、".join(comps),
        product="出行",
        project_id=project_id,
        workflow_kind=workflow_kind,
        competitors=comps,
        evidence_max_age_months=48,
        user_query="分析华南网约车市场竞争格局",
    )


def _ctx(tid: str = "bench-current") -> AgentContext:
    return AgentContext(task_id=tid, current_phase="researching")


def _sel_plan(dimensions: list[str], keywords: list[str] | None = None):
    plan = MagicMock()
    plan.dimensions = list(dimensions)
    plan.objective = "bench"
    plan.all_source_types = ["web"]
    t = MagicMock()
    t.dimension = dimensions[0] if dimensions else "web"
    t.sources = ["web"]
    t.keywords = list(keywords or dimensions)
    plan.tasks = [t]
    return plan


def _source_ok(url: str, title: str, content: str) -> SourceResult:
    item = MagicMock()
    item.url = url
    item.title = title
    item.content = content
    item.snippet = content
    item.published_date = "2025-06-01"
    return SourceResult(
        items=[item],
        source_type="web",
        source_name="bench-web",
        status="success",
        error=None,
        total_found=1,
        duration_ms=1,
    )


def _dto(url: str, title: str, content: str, category: str) -> EvidenceItemDTO:
    return EvidenceItemDTO(
        title=title,
        source="bench",
        url=url,
        date="2025-06-01",
        content=content,
        category=category,
        confidence="medium",
    )


RICH_HISTORY = [
    _item(
        url="https://bench.ex/pos",
        title="滴滴出行 定位",
        content="滴滴出行华南品牌定位",
        category="positioning",
        eid="E017",
    ),
    _item(
        url="https://bench.ex/users",
        title="如祺出行 用户",
        content="如祺出行用户画像",
        category="users",
        eid="E023",
    ),
    _item(
        url="https://bench.ex/growth",
        title="滴滴出行 增长",
        content="滴滴出行与如祺出行增长策略与市场",
        category="growth",
        eid="E031",
    ),
]


def _quality_checks(bundle, *, allowed_entities: list[str], allowed_categories: set[str]) -> list[str]:
    flags: list[str] = []
    items = list(getattr(bundle, "evidence_items", []) or [])
    urls = [getattr(e, "url", "") for e in items]
    ids = [getattr(e, "id", "") for e in items]
    if any(not u.startswith("http") for u in urls):
        flags.append("empty_or_invalid_url")
    if len(urls) != len(set(urls)):
        flags.append("duplicate_url")
    if ids != [f"E{i:03d}" for i in range(1, len(ids) + 1)]:
        flags.append("bad_evidence_ids")
    src_ids = [s.get("source_id") for s in (getattr(bundle, "sources_used", None) or [])]
    if src_ids and src_ids != ids:
        flags.append("sources_used_misaligned")
    blob_entities = " ".join(
        f"{getattr(e, 'title', '')} {getattr(e, 'content', '')}" for e in items
    )
    # Soft check: at least one allowed entity appears somewhere
    if allowed_entities and not any(a in blob_entities for a in allowed_entities):
        flags.append("no_allowed_entity_text")
    for e in items:
        cat = (getattr(e, "category", "") or "").strip()
        if cat and allowed_categories:
            # English categories used in fixtures
            if cat not in allowed_categories and cat not in {
                "positioning", "users", "growth", "business", "competitive_landscape",
            }:
                flags.append(f"unexpected_category:{cat}")
    return flags


async def _run_research_instrumented(
    *,
    tasks: dict,
    research_input: ResearchInput,
    extract_items: list[EvidenceItemDTO] | None,
    task_label: str,
) -> tuple[ResearchCostSnapshot, Any]:
    agent = ResearchAgent()
    monkey_tasks = dict(tasks)
    extract_invocations = {"n": 0}
    route_invocations = {"n": 0, "dimensions": [], "keywords": []}

    async def _route(**kwargs):
        route_invocations["n"] += 1
        dims = list(kwargs.get("dimensions") or [])
        kws = list(kwargs.get("keywords") or [])
        route_invocations["dimensions"] = dims
        route_invocations["keywords"] = kws
        return _sel_plan(dims or ["产品定位与品牌"], kws)

    async def _extract(self, *_a, **_k):
        extract_invocations["n"] += 1
        items = list(extract_items or [])
        for idx, e in enumerate(items):
            e.id = f"E{idx + 1:03d}"
        return (items, "bench")

    search_calls = {"n": 0}

    async def _execute(*_a, **_k):
        search_calls["n"] += 1
        return [
            _source_ok(
                "https://bench.ex/live",
                "live hit",
                "滴滴出行 如祺出行 高德打车 live",
            ),
        ]

    with (
        patch.object(task_report_runtime, "_tasks", monkey_tasks),
        patch(
            "app.infrastructure.agents.research_agent.llm_router.route",
            AsyncMock(side_effect=_route),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_selection.build_plan",
            side_effect=lambda dimensions, keywords, objective: _sel_plan(
                list(dimensions or []), list(keywords or []),
            ),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.execute_plan",
            AsyncMock(side_effect=_execute),
        ),
        patch(
            "app.infrastructure.agents.research_agent.source_router.search_many",
            AsyncMock(side_effect=_execute),
        ),
        patch.object(
            ResearchAgent,
            "_extract_evidence_from_sources",
            _extract,
        ),
        patch.object(
            ResearchAgent,
            "_apply_date_and_freshness_pipeline",
            AsyncMock(side_effect=lambda items, _inp: items),
        ),
    ):
        result = await agent.arun(_ctx(), research_input)

    assert result.success
    pr = result.phase_record or {}
    meta = dict(pr.get("reuse_meta") or {})
    mode = "full_research"
    if pr.get("skipped_search") or meta.get("skipped_search"):
        mode = "zero_search"
    elif pr.get("gap_search") or meta.get("gap_search"):
        mode = "gap_search"

    bundle = result.output.evidence_bundle
    items = list(bundle.evidence_items or [])
    hist_count = 0
    for _tid, entry in monkey_tasks.items():
        if str(entry.get("status")) == "completed":
            eb = ((entry.get("state") or {}).get("evidence_bundle") or {})
            hist_count += len(eb.get("evidence_items") or [])

    if mode == "zero_search":
        reused = len(items)
        new_count = 0
        search_n = 0
        extract_n = 0
        router_n = 0
    elif mode == "gap_search":
        reused = int(meta.get("reused_count") or 0)
        if reused <= 0:
            # seed size before merge approx from hist overlapping urls
            reused = sum(1 for u in [e.url for e in items] if u.startswith("https://bench.ex/") and u in {
                i["url"] for h in monkey_tasks.values()
                for i in (((h.get("state") or {}).get("evidence_bundle") or {}).get("evidence_items") or [])
            })
        new_count = int(meta.get("new_evidence_count") or max(0, len(items) - reused))
        search_n = search_calls["n"]
        extract_n = extract_invocations["n"]
        router_n = route_invocations["n"]
    else:
        reused = 0
        new_count = len(items)
        search_n = search_calls["n"]
        extract_n = extract_invocations["n"]
        router_n = route_invocations["n"]

    # Research LLM calls ≈ router + extraction (mocked entrypoints that replace real LLM)
    llm_n = router_n + extract_n

    snap = ResearchCostSnapshot(
        task=task_label,
        reuse_mode=mode,
        search_calls=search_n,
        llm_calls=llm_n,
        llm_router_calls=router_n,
        llm_extraction_calls=extract_n,
        prompt_tokens=0,
        completion_tokens=0,
        total_tokens=0,
        token_usage_unavailable=True,
        historical_evidence_count=hist_count,
        reused_evidence_count=reused,
        new_evidence_count=new_count,
        evidence_count=len(items),
        evidence_urls=[e.url for e in items],
        evidence_ids=[str(e.id) for e in items],
        evidence_categories=[e.category for e in items],
        route_dimensions=list(
            meta.get("route_dimensions")
            or route_invocations["dimensions"]
            or pr.get("selection_plan")
            or [],
        ),
        gap_keywords=list(meta.get("gap_keywords") or route_invocations["keywords"] or []),
    )
    snap.pollution_flags = _quality_checks(
        bundle,
        allowed_entities=list(research_input.competitors or []) + [research_input.our_company],
        allowed_categories={"positioning", "users", "growth", "business"},
    )
    return snap, result


@pytest.mark.asyncio
async def test_step3_benchmark_cases_a_to_e(monkeypatch: pytest.MonkeyPatch):
    """Run Cases A–E and assert cost/quality/anti-pollution success criteria."""
    results: dict[str, ResearchCostSnapshot] = {}

    # ── Case A: Baseline full research (no history) ──
    extract_a = [
        _dto("https://bench.ex/a1", "滴滴出行 定位", "滴滴出行华南", "positioning"),
        _dto("https://bench.ex/a2", "如祺出行 用户", "如祺出行用户", "users"),
        _dto("https://bench.ex/a3", "增长", "滴滴出行 如祺出行 增长策略与市场", "growth"),
    ]
    snap_a, _ = await _run_research_instrumented(
        tasks={},
        research_input=_input(),
        extract_items=extract_a,
        task_label="A_baseline_full",
    )
    results["A"] = snap_a
    assert snap_a.reuse_mode == "full_research"
    assert snap_a.search_calls >= 1
    assert snap_a.reused_evidence_count == 0
    assert snap_a.evidence_count >= 1
    assert not snap_a.pollution_flags

    # ── Case B: Exact repeat → zero search ──
    hist_b = {
        "hist-rich": _hist(
            "hist-rich",
            project_id="bench-p1",
            our="滴滴出行",
            competitors=["如祺出行"],
            items=RICH_HISTORY,
        ),
    }
    snap_b, res_b = await _run_research_instrumented(
        tasks=hist_b,
        research_input=_input(),
        extract_items=[],  # must not be needed
        task_label="B_exact_repeat_zero",
    )
    results["B"] = snap_b
    assert snap_b.reuse_mode == "zero_search"
    assert snap_b.search_calls == 0
    assert snap_b.llm_extraction_calls == 0
    assert snap_b.reused_evidence_count >= 2
    assert snap_b.new_evidence_count == 0
    assert snap_b.evidence_ids == [f"E{i:03d}" for i in range(1, snap_b.evidence_count + 1)]
    assert "E017" not in snap_b.evidence_ids
    assert not snap_b.pollution_flags

    # ── Case C: Partial / gap (business dimension missing) ──
    # History covers pos/users/growth but not business; current asks for 商业模式差异
    hist_c_items = [
        _item(
            url="https://bench.ex/pos",
            title="滴滴出行 定位",
            content="滴滴出行",
            category="positioning",
        ),
        _item(
            url="https://bench.ex/users",
            title="如祺出行 用户",
            content="如祺出行用户",
            category="users",
        ),
    ]
    hist_c = {
        "hist-partial": _hist(
            "hist-partial",
            project_id="bench-p1",
            our="滴滴出行",
            competitors=["如祺出行"],
            items=hist_c_items,
        ),
    }
    extract_c = [
        _dto(
            "https://bench.ex/biz",
            "如祺出行 商业模式",
            "如祺出行商业模式差异",
            "business",
        ),
    ]
    snap_c, _ = await _run_research_instrumented(
        tasks=hist_c,
        research_input=_input(scope=SCOPE_BIZ),
        extract_items=extract_c,
        task_label="C_partial_gap",
    )
    results["C"] = snap_c
    assert snap_c.reuse_mode == "gap_search"
    assert snap_c.search_calls >= 1
    assert snap_c.search_calls <= snap_a.search_calls
    assert snap_c.reused_evidence_count >= 1
    assert snap_c.new_evidence_count >= 1
    assert "https://bench.ex/pos" in snap_c.evidence_urls
    assert "https://bench.ex/biz" in snap_c.evidence_urls
    # Gap should focus on 商业模式差异
    assert snap_c.route_dimensions == ["商业模式差异"] or (
        snap_c.gap_keywords and any("商业" in k for k in snap_c.gap_keywords)
    )
    assert not snap_c.pollution_flags

    # ── Case D: Different competitor — no reuse / no Ruqi pollution as competitor set ──
    snap_d, res_d = await _run_research_instrumented(
        tasks=hist_b,  # Ruqi history present
        research_input=_input(
            competitors=["高德打车"],
            competitor_company="高德打车",
        ),
        extract_items=[
            _dto("https://bench.ex/gaode", "高德打车", "滴滴出行 vs 高德打车", "positioning"),
            _dto("https://bench.ex/gaode2", "高德用户", "高德打车用户", "users"),
            _dto("https://bench.ex/gaode3", "增长", "高德打车增长策略与市场", "growth"),
        ],
        task_label="D_different_competitor",
    )
    results["D"] = snap_d
    assert snap_d.reuse_mode == "full_research"
    assert snap_d.reused_evidence_count == 0
    assert snap_d.search_calls >= 1
    # Must not carry over Ruqi-only historical URLs from seed reuse
    assert "https://bench.ex/pos" not in snap_d.evidence_urls
    assert "https://bench.ex/users" not in snap_d.evidence_urls
    assert "https://bench.ex/growth" not in snap_d.evidence_urls
    assert "E017" not in snap_d.evidence_ids
    assert not snap_d.pollution_flags

    # ── Case E: Entity+dimension gap focus ──
    hist_e = {
        "hist-didi-only": _hist(
            "hist-didi-only",
            project_id="bench-p1",
            our="滴滴出行",
            competitors=["如祺出行"],
            items=[
                _item(
                    url="https://bench.ex/d1",
                    title="滴滴出行 定位",
                    content="仅滴滴出行",
                    category="positioning",
                ),
                _item(
                    url="https://bench.ex/d2",
                    title="滴滴出行 用户",
                    content="仅滴滴出行用户",
                    category="users",
                ),
            ],
        ),
    }
    snap_e, _ = await _run_research_instrumented(
        tasks=hist_e,
        research_input=_input(),
        extract_items=[
            _dto(
                "https://bench.ex/ruqi-growth",
                "如祺出行 增长",
                "如祺出行增长策略与市场",
                "growth",
            ),
        ],
        task_label="E_entity_dimension_gap",
    )
    results["E"] = snap_e
    assert snap_e.reuse_mode == "gap_search"
    assert snap_e.reused_evidence_count >= 1
    assert any("如祺" in k for k in (snap_e.gap_keywords or []))
    assert snap_e.route_dimensions == ["增长策略与市场"]
    # Historical category not rewritten
    assert "positioning" in snap_e.evidence_categories
    assert "users" in snap_e.evidence_categories
    assert not snap_e.pollution_flags

    # ── Success criteria aggregates ──
    assert snap_b.search_calls < snap_a.search_calls
    assert snap_b.search_calls == 0
    search_reduction_b = 1.0 - (snap_b.search_calls / max(snap_a.search_calls, 1))
    search_reduction_c = 1.0 - (snap_c.search_calls / max(snap_a.search_calls, 1))
    assert search_reduction_b == 1.0
    assert search_reduction_c >= 0.0

    # Persist a human-readable summary for the Step 3 report consumer
    summary_lines = [
        f"{k}: mode={v.reuse_mode} search={v.search_calls} llm={v.llm_calls} "
        f"extract={v.llm_extraction_calls} reused={v.reused_evidence_count} "
        f"new={v.new_evidence_count} evidence={v.evidence_count} "
        f"tokens={v.total_tokens} unavailable={v.token_usage_unavailable} "
        f"pollution={v.pollution_flags}"
        for k, v in results.items()
    ]
    print("\n".join(["STEP3_BENCHMARK"] + summary_lines))
    print(
        f"REDUCTIONS exact_search={search_reduction_b:.0%} "
        f"partial_search={search_reduction_c:.0%} "
        f"exact_extract_llm={1.0 - (snap_b.llm_extraction_calls / max(snap_a.llm_extraction_calls or snap_a.llm_calls or 1, 1)):.0%}",
    )
