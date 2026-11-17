"""Evidence Reuse V1 Step 1 — judgment layer unit tests."""

from __future__ import annotations

from datetime import date

import pytest

from app.application.services.evidence_reuse import (
    CurrentReuseRequest,
    EvidenceReuseService,
    competitor_combination_key,
    merge_and_renumber_evidence,
    normalize_entity_name,
)


TODAY = date(2026, 9, 8)


def _item(
    *,
    url: str,
    title: str,
    content: str,
    category: str,
    date_str: str = "2025-06-01",
    eid: str = "E099",
    source: str = "Tavily",
) -> dict:
    return {
        "id": eid,
        "title": title,
        "source": source,
        "source_type": "web",
        "url": url,
        "date": date_str,
        "content": content,
        "confidence": "medium",
        "category": category,
        "extracted_at": "2026-09-01T00:00:00",
    }


def _deep_task(
    task_id: str,
    *,
    project_id: str,
    our: str,
    competitors: list[str],
    items: list[dict],
    workflow_kind: str | None = "deep_analysis",
    status: str = "completed",
    entry_wk: str | None = None,
) -> dict:
    optional: dict = {
        "competitors": competitors,
        "workflow_kind": workflow_kind,
    }
    return {
        "task_id": task_id,
        "status": status,
        "project_id": project_id,
        "workflow_kind": entry_wk if entry_wk is not None else (
            workflow_kind if workflow_kind == "intelligence_collection" else None
        ),
        "state": {
            "user_input": {
                "our_company": our,
                "competitor_company": "、".join(competitors) if competitors else "",
                "optional": optional,
            },
            "validated_input": {
                "our_company": our,
                "competitor_company": "、".join(competitors) if competitors else "",
            },
            "evidence_bundle": {"evidence_items": items},
            "research_plan": {
                "analysis_scope": ["产品定位与品牌", "用户画像与行为变化"],
            },
        },
    }


@pytest.fixture
def svc() -> EvidenceReuseService:
    return EvidenceReuseService()


def test_case1_same_project_same_peers_fresh_sufficient(svc: EvidenceReuseService):
    hist = _deep_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行 定位分析",
                content="滴滴出行在广东市场的品牌定位",
                category="positioning",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行 用户画像",
                content="如祺出行用户行为与画像变化",
                category="users",
            ),
        ],
    )
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert result.reuse_disabled is False
    assert result.reuse_meta["reused_count"] > 0
    assert result.sufficient is True
    assert result.gap_entities == []
    assert result.gap_dimensions == []


def test_case2_different_competitors_no_reuse(svc: EvidenceReuseService):
    hist = _deep_task(
        "hist-ruqi",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行 vs 如祺出行",
                content="滴滴出行与如祺出行对比",
                category="positioning",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行用户",
                content="如祺出行用户画像",
                category="users",
            ),
        ],
    )
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["高德打车"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"hist-ruqi": hist},
        today=TODAY,
    )
    assert result.reuse_meta["reused_count"] == 0
    assert result.reusable_evidence == []


def test_case3_different_project_no_reuse(svc: EvidenceReuseService):
    hist = _deep_task(
        "hist-1",
        project_id="other-project",
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
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert result.reuse_meta["reused_count"] == 0


def test_case4_collection_reuse_disabled(svc: EvidenceReuseService):
    hist = _deep_task(
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
        ],
    )
    # Current is collection
    current_disabled = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌"],
            workflow_kind="intelligence_collection",
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert current_disabled.reuse_disabled is True
    assert current_disabled.reuse_meta["reused_count"] == 0

    # Historical is collection — Deep current must not reuse it
    coll = _deep_task(
        "coll-1",
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
        workflow_kind="intelligence_collection",
        entry_wk="intelligence_collection",
    )
    hist_disabled = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"coll-1": coll},
        today=TODAY,
    )
    assert hist_disabled.reuse_meta["reused_count"] == 0


def test_case5_expired_evidence_excluded(svc: EvidenceReuseService):
    hist = _deep_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/old",
                title="滴滴出行 旧闻",
                content="滴滴出行与如祺出行",
                category="positioning",
                date_str="2018-01-01",
            ),
            _item(
                url="https://ex.com/old2",
                title="如祺出行 用户",
                content="如祺出行用户画像",
                category="users",
                date_str="2019-01-01",
            ),
        ],
    )
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
            evidence_max_age_months=48,
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert result.reusable_evidence == []
    assert result.reuse_meta["reused_count"] == 0


def test_case6_missing_one_entity_gap(svc: EvidenceReuseService):
    hist = _deep_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行 定位",
                content="仅讨论滴滴出行品牌定位，未提对方",
                category="positioning",
            ),
            _item(
                url="https://ex.com/b",
                title="滴滴出行 用户",
                content="滴滴出行用户画像变化",
                category="users",
            ),
        ],
    )
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert result.sufficient is False
    assert any("如祺" in g for g in result.gap_entities)
    assert result.reuse_meta["reused_count"] >= 1  # Didi-side items still reusable


def test_case7_missing_one_scope_gap(svc: EvidenceReuseService):
    hist = _deep_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴出行 用户",
                content="滴滴出行用户画像",
                category="users",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行 用户",
                content="如祺出行用户行为",
                category="users",
            ),
        ],
    )
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert result.sufficient is False
    assert "产品定位与品牌" in result.gap_dimensions
    assert "用户画像与行为变化" not in result.gap_dimensions


def test_case8_url_dedupe(svc: EvidenceReuseService):
    hist = _deep_task(
        "hist-1",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/same",
                title="滴滴出行 定位",
                content="滴滴出行",
                category="positioning",
                eid="E017",
            ),
            _item(
                url="https://ex.com/same",
                title="如祺出行 也被写进同一 URL",
                content="如祺出行与滴滴出行",
                category="users",
                eid="E023",
            ),
        ],
    )
    # Also duplicate across two historical tasks
    hist2 = _deep_task(
        "hist-2",
        project_id="p1",
        our="滴滴出行",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/same",
                title="滴滴出行 再次",
                content="滴滴出行 如祺出行",
                category="positioning",
                eid="E031",
            ),
        ],
    )
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"hist-1": hist, "hist-2": hist2},
        today=TODAY,
    )
    urls = [i["url"] for i in result.reusable_evidence]
    assert urls.count("https://ex.com/same") == 1


def test_case9_renumber_e001(svc: EvidenceReuseService):
    merged = merge_and_renumber_evidence(
        [
            _item(
                url="https://ex.com/1",
                title="a",
                content="a",
                category="users",
                eid="E017",
            ),
            _item(
                url="https://ex.com/2",
                title="b",
                content="b",
                category="users",
                eid="E023",
            ),
            _item(
                url="https://ex.com/2",
                title="dup",
                content="dup",
                category="users",
                eid="E031",
            ),
        ],
        [],
    )
    assert [m["id"] for m in merged] == ["E001", "E002"]
    assert len(merged) == 2


def test_case10_memory_not_involved(svc: EvidenceReuseService, monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []

    def _boom(*_a, **_k):
        calls.append("memory")
        raise AssertionError("Memory must not be read by EvidenceReuseService")

    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.project_memory_store.ProjectMemoryStore.get",
        _boom,
        raising=False,
    )
    # Inject fake memory module path if imported
    import app.application.services.evidence_reuse as mod

    assert "memory" not in mod.__file__.lower() or "evidence_reuse" in mod.__file__

    hist = _deep_task(
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
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert calls == []
    assert all("key_findings" not in str(i) for i in result.reusable_evidence)
    # Source of truth is evidence_bundle items only
    assert result.reuse_meta["reused_count"] == 2


def test_unmapped_scope_is_gap(svc: EvidenceReuseService):
    hist = _deep_task(
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
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["完全无法映射的自定义维度XYZ"],
            workflow_kind="deep_analysis",
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert result.sufficient is False
    assert "完全无法映射的自定义维度XYZ" in result.gap_dimensions
    assert result.reuse_meta["reused_count"] == 0


def test_competitor_order_insensitive():
    a = competitor_combination_key("滴滴出行", ["如祺出行", "高德打车"])
    b = competitor_combination_key("滴滴出行", ["高德打车", "如祺出行"])
    assert a == b
    assert normalize_entity_name("滴滴打车") == normalize_entity_name("滴滴出行")


def test_alias_allows_didi_variant_same_combo(svc: EvidenceReuseService):
    """滴滴打车 vs 如祺 and 滴滴出行 vs 如祺 share normalized combo."""
    hist = _deep_task(
        "hist-1",
        project_id="p1",
        our="滴滴打车",
        competitors=["如祺出行"],
        items=[
            _item(
                url="https://ex.com/a",
                title="滴滴打车 定位",
                content="滴滴在华南",
                category="positioning",
            ),
            _item(
                url="https://ex.com/b",
                title="如祺出行 用户",
                content="如祺出行用户",
                category="users",
            ),
        ],
    )
    result = svc.evaluate(
        CurrentReuseRequest(
            project_id="p1",
            our_company="滴滴出行",
            competitors=["如祺出行"],
            analysis_scope=["产品定位与品牌", "用户画像与行为变化"],
            workflow_kind="deep_analysis",
        ),
        {"hist-1": hist},
        today=TODAY,
    )
    assert result.reuse_meta["reused_count"] > 0
