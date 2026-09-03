"""PR30: Full mode clustering progress + 720s watchdog hardening."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import EvidenceItemDTO
from app.infrastructure.workflow.analysis_mode import get_mode_config
from app.infrastructure.workflow.nodes import (
    _run_full_evidence_clustering,
    compare_node,
    insight_node,
    report_node,
    research_node,
    review_node,
)
from app.infrastructure.workflow.progress_hints import RESEARCH_PROGRESS_HINTS
from app.infrastructure.workflow.state import WorkflowState
from app.infrastructure.workflow.workflow_budget import (
    COMPARE_BUDGET_ELAPSED_S,
    HARD_LLM_CUTOFF_S,
    INSIGHT_SKIP_ELAPSED_S,
    REPORT_COMPACT_ELAPSED_S,
    REVIEW_SKIP_ELAPSED_S,
    should_block_llm_for_budget,
    should_skip_insight_for_budget,
    should_skip_review_for_budget,
    should_use_compact_report,
)


def _full_state(**extra) -> WorkflowState:
    base = WorkflowState(
        task_id="test-pr30",
        user_input={
            "our_company": "Acme",
            "competitor_company": "Beta",
            "product": "Widget",
            "objective": "product_improvement",
            "optional": {"analysis_mode": "full"},
        },
        validated_input={
            "our_company": "Acme",
            "competitor_company": "Beta",
            "product": "Widget",
            "objective": "product_improvement",
        },
        current_phase="planned",
        phase_history=[],
        errors=[],
        progress=20.0,
        research_plan={"objective": "test", "analysis_scope": ["features"]},
        evidence_bundle={"evidence_items": []},
        gap_analysis={},
        strategic_insights={},
        report_document={"formats": {"markdown": "# Report\n\nBody"}},
        workflow_started_at=time.monotonic(),
    )
    base.update(extra)
    return base


def _evidence_bundle_obj(n: int = 3):
    items = [
        EvidenceItemDTO(
            id=f"E{i + 1:03d}",
            title=f"T{i}",
            source="web",
            content=f"C{i}",
            url=f"https://example.com/{i}",
            date="2025-01-01",
            confidence="medium",
            category="features",
        )
        for i in range(n)
    ]
    return SimpleNamespace(evidence_items=items)


class TestClusteringProgress:
    @pytest.mark.asyncio
    async def test_full_clustering_emits_42_and_44_hints(self):
        state = _full_state()
        cfg = get_mode_config("full")
        budget = {"workflow_budget_meta": {}}
        touches: list[float] = []

        async def fake_cluster(**kwargs):
            await asyncio.sleep(0.01)
            return [SimpleNamespace(to_dict=lambda: {"cluster_id": "c1", "topic": "t"})]

        with patch(
            "app.infrastructure.tools.evidence_clustering.evidence_clustering.cluster",
            new=AsyncMock(side_effect=fake_cluster),
        ), patch(
            "app.infrastructure.persistence.task_report_runtime.touch_task_progress",
            side_effect=lambda *a, **kw: touches.append(float(kw.get("progress", 0))),
        ):
            clusters, meta = await _run_full_evidence_clustering(
                state, cfg, _evidence_bundle_obj(), budget,
            )

        assert len(clusters) == 1
        assert 42.0 in touches
        assert 44.0 in touches
        assert meta.get("clustering_elapsed_s", 0) >= 0

    @pytest.mark.asyncio
    async def test_clustering_timeout_skips_without_fail(self):
        from dataclasses import replace

        state = _full_state()
        cfg = replace(get_mode_config("full"), clustering_timeout_s=0.05)
        budget = {"workflow_budget_meta": {}}

        async def slow_cluster(**kwargs):
            await asyncio.sleep(0.2)

        with patch(
            "app.infrastructure.tools.evidence_clustering.evidence_clustering.cluster",
            new=AsyncMock(side_effect=slow_cluster),
        ):
            clusters, meta = await _run_full_evidence_clustering(
                state, cfg, _evidence_bundle_obj(), budget,
            )

        assert clusters == []
        assert meta.get("clustering_timeout") is True
        assert meta.get("clustering_skipped") is True

    @pytest.mark.asyncio
    async def test_fast_research_skips_clustering_branch(self):
        state = _full_state(
            user_input={
                "our_company": "Acme",
                "competitor_company": "Beta",
                "product": "Widget",
                "objective": "product_improvement",
                "optional": {"analysis_mode": "fast"},
            },
        )
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.output.evidence_bundle = _evidence_bundle_obj()
        mock_result.output.quality_report = MagicMock(model_dump=lambda: {})
        mock_result.phase_record = {"phase": "researched", "status": "completed"}

        with patch(
            "app.infrastructure.agents.research_agent.ResearchAgent.aexecute",
            new=AsyncMock(return_value=mock_result),
        ), patch(
            "app.infrastructure.workflow.nodes._run_full_evidence_clustering",
            new=AsyncMock(),
        ) as cluster_mock:
            result = await research_node(state)

        cluster_mock.assert_not_awaited()
        assert result["progress"] == 40.0
        assert result["stage_hint"] == RESEARCH_PROGRESS_HINTS[40.0]


class TestWatchdogThresholds:
    def test_review_skip_at_716s(self):
        state = _full_state(workflow_started_at=time.monotonic() - 716.0)
        cfg = get_mode_config("full")
        assert should_skip_review_for_budget(state, cfg) is True

    def test_compact_report_at_665s(self):
        state = _full_state(workflow_started_at=time.monotonic() - 665.0)
        cfg = get_mode_config("full")
        assert should_use_compact_report(state, cfg) is True

    def test_insight_skip_at_632s(self):
        state = _full_state(workflow_started_at=time.monotonic() - 632.0)
        cfg = get_mode_config("full")
        assert should_skip_insight_for_budget(state, cfg) is True

    def test_block_llm_at_720s(self):
        state = _full_state(workflow_started_at=time.monotonic() - 721.0)
        cfg = get_mode_config("full")
        assert should_block_llm_for_budget(state, cfg) is True

    def test_fast_budget_unchanged(self):
        cfg = get_mode_config("fast")
        assert cfg.mode_total_budget_s == 360.0
        state = _full_state(
            workflow_started_at=time.monotonic() - 400.0,
            user_input={"optional": {"analysis_mode": "fast"}},
        )
        assert should_skip_review_for_budget(state, cfg) is False
        assert should_block_llm_for_budget(state, cfg) is False


class TestWatchdogNodeSkips:
    @pytest.mark.asyncio
    async def test_review_skipped_no_llm_at_716s(self):
        state = _full_state(current_phase="reported")
        state["workflow_started_at"] = time.monotonic() - 716.0
        with patch("app.infrastructure.agents.review_agent.ReviewAgent.aexecute", new=AsyncMock()) as llm:
            result = await review_node(state)
        llm.assert_not_awaited()
        assert result["review_result"]["review_skipped_total_budget"] is True

    @pytest.mark.asyncio
    async def test_insight_skipped_at_632s(self):
        state = _full_state(current_phase="compared")
        state["workflow_started_at"] = time.monotonic() - 632.0
        with patch("app.infrastructure.agents.insight_agent.InsightAgent.aexecute", new=AsyncMock()) as llm:
            result = await insight_node(state)
        llm.assert_not_awaited()
        assert result["insights"] == {}
        assert result["workflow_budget_meta"]["insight_skipped_budget"] is True

    @pytest.mark.asyncio
    async def test_compare_skipped_at_600s(self):
        state = _full_state(current_phase="researched", clusters=[{"cluster_id": "c1"}])
        state["workflow_started_at"] = time.monotonic() - 601.0
        with patch("app.infrastructure.agents.compare_agent.CompareAgent.aexecute", new=AsyncMock()) as llm:
            result = await compare_node(state)
        llm.assert_not_awaited()
        assert result["workflow_budget_meta"]["compare_skipped_budget"] is True

    @pytest.mark.asyncio
    async def test_report_fallback_no_llm_at_721s(self):
        state = _full_state(current_phase="strategized")
        state["workflow_started_at"] = time.monotonic() - 721.0
        with patch("app.infrastructure.agents.report_agent.ReportAgent.aexecute", new=AsyncMock()) as llm:
            result = await report_node(state)
        llm.assert_not_awaited()
        assert result["current_phase"] == "reported"
        assert result["workflow_budget_meta"]["report_skipped_budget"] is True
        assert result["report_document"]["formats"]["markdown"]

    @pytest.mark.asyncio
    async def test_report_compact_flag_at_665s(self):
        state = _full_state(current_phase="strategized")
        state["workflow_started_at"] = time.monotonic() - 665.0
        captured: dict = {}

        async def capture_execute(ctx, report_input):
            captured["compact"] = report_input.compact_report
            fallback = MagicMock()
            fallback.success = True
            fallback.output.report_document = MagicMock(
                model_dump=lambda: {"formats": {"markdown": "# ok"}}
            )
            fallback.phase_record = {"phase": "reported", "status": "completed"}
            return fallback

        with patch(
            "app.infrastructure.agents.report_agent.ReportAgent.aexecute",
            new=AsyncMock(side_effect=capture_execute),
        ):
            await report_node(state)

        assert captured.get("compact") is True


class TestFullModeConfig:
    def test_clustering_timeout_configured(self):
        cfg = get_mode_config("full")
        assert cfg.clustering_timeout_s == 60.0

    def test_watchdog_constants(self):
        assert REVIEW_SKIP_ELAPSED_S == 715.0
        assert HARD_LLM_CUTOFF_S == 720.0
        assert REPORT_COMPACT_ELAPSED_S == 660.0
        assert INSIGHT_SKIP_ELAPSED_S == 630.0
        assert COMPARE_BUDGET_ELAPSED_S == 600.0
