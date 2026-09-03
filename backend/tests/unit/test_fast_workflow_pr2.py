"""PR2: Fast mode skip Compare, plan trim, clustering skip, report fast prompt."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import PlannerInput, ReportInput
from app.infrastructure.agents.planner_agent import PlannerAgent
from app.infrastructure.agents.report_prompt import build_report_prompt
from app.infrastructure.workflow.analysis_mode import (
    FAST_MAX_PLAN_DIMENSIONS,
    get_mode_config,
    trim_research_plan_for_mode,
)
from app.infrastructure.workflow.graph import (
    _route_after_compare,
    _route_after_research,
    build_workflow_graph,
)
from app.infrastructure.workflow.nodes import plan_node, report_node, research_node
from app.infrastructure.workflow.state import WorkflowState


def _state(*, mode: str = "fast") -> WorkflowState:
    return WorkflowState(
        task_id="test-pr2",
        user_input={
            "our_company": "Acme",
            "competitor_company": "Beta",
            "product": "Widget",
            "objective": "product_improvement",
            "optional": {"analysis_mode": mode},
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
        progress=15.0,
        research_plan={
            "objective": "test",
            "analysis_scope": ["features", "growth", "business", "users", "ux"],
        },
    )


class TestSkipCompareConfig:
    def test_fast_skip_compare_enabled(self):
        assert get_mode_config("fast").skip_compare is True

    def test_full_skip_compare_disabled(self):
        assert get_mode_config("full").skip_compare is False


class TestGraphRouting:
    def test_fast_routes_research_to_report(self):
        assert _route_after_research(_state(mode="fast")) == "report_node"

    def test_full_routes_research_to_compare(self):
        assert _route_after_research(_state(mode="full")) == "compare_node"

    def test_fast_after_compare_still_goes_to_report(self):
        """Insight/Strategy already skipped for fast via _route_after_compare."""
        assert _route_after_compare(_state(mode="fast")) == "report_node"

    def test_graph_has_research_conditional_edges(self):
        graph = build_workflow_graph()
        # Compiled graph exposes nodes; routing is wired at compile time.
        assert "research_node" in graph.nodes
        assert "compare_node" in graph.nodes
        assert "report_node" in graph.nodes


class TestPlanTrim:
    def test_fast_plan_capped_to_two_dimensions(self):
        cfg = get_mode_config("fast")
        plan = {"analysis_scope": ["a", "b", "c", "d", "e"]}
        trimmed = trim_research_plan_for_mode(plan, cfg)
        assert len(trimmed["analysis_scope"]) == FAST_MAX_PLAN_DIMENSIONS

    def test_full_plan_not_trimmed(self):
        cfg = get_mode_config("full")
        plan = {"analysis_scope": ["a", "b", "c", "d", "e"]}
        trimmed = trim_research_plan_for_mode(plan, cfg)
        assert len(trimmed["analysis_scope"]) == 5

    @pytest.mark.asyncio
    async def test_plan_node_applies_trim_on_mock_fallback(self):
        state = _state(mode="fast")
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await plan_node(state)
        assert len(result["research_plan"]["analysis_scope"]) <= FAST_MAX_PLAN_DIMENSIONS

    def test_mock_plan_trimmed_for_fast(self):
        cfg = get_mode_config("fast")
        pi = PlannerInput(
            our_company="A",
            competitor_company="B",
            product="P",
            objective="product_improvement",
        )
        mock = PlannerAgent._mock_plan(pi)
        trimmed = trim_research_plan_for_mode(mock.model_dump(), cfg)
        assert len(trimmed["analysis_scope"]) <= FAST_MAX_PLAN_DIMENSIONS


class TestResearchClustering:
    @pytest.mark.asyncio
    async def test_fast_skips_clustering(self):
        state = _state(mode="fast")
        eb = MagicMock()
        eb.evidence_items = [
            MagicMock(
                id="E001",
                title="t",
                content="c",
                source_type="web",
                confidence="medium",
                date="",
                quality_score={},
            )
        ]
        eb.model_dump.return_value = {"evidence_items": [{"id": "E001"}]}

        agent_result = MagicMock()
        agent_result.success = True
        agent_result.output.evidence_bundle = eb
        agent_result.output.quality_report = MagicMock(model_dump=lambda: {})
        agent_result.phase_record = {"phase": "researching", "status": "completed"}

        with patch("app.infrastructure.workflow.nodes.ResearchAgent") as mock_cls:
            mock_cls.return_value.aexecute = AsyncMock(return_value=agent_result)
            with patch("asyncio.wait_for", new=AsyncMock(return_value=agent_result)):
                with patch(
                    "app.infrastructure.tools.evidence_clustering.evidence_clustering.cluster",
                    new=AsyncMock(),
                ) as mock_cluster:
                    result = await research_node(state)

        mock_cluster.assert_not_called()
        assert result["clusters"] == []
        last_phase = result.get("phase_history", [{}])[-1]
        assert last_phase.get("skipped_compare") is True


class TestReportFastPrompt:
    def test_fast_prompt_includes_evidence_only_instructions(self):
        prompt = build_report_prompt(
            our_company="A",
            competitor_company="B",
            product="P",
            objective="product_improvement",
            evidence_json='[{"id":"E001"}]',
            gap_json="{}",
            strategy_json="{}",
            fast_mode=True,
        )
        assert "快速模式" in prompt
        assert "基于证据整理" in prompt
        assert "2500-3000" in prompt
        assert "完整 13 章" in prompt

    def test_standard_prompt_keeps_strategy_reminder(self):
        prompt = build_report_prompt(
            our_company="A",
            competitor_company="B",
            product="P",
            objective="product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
            fast_mode=False,
        )
        assert "保持 Strategy 结论不变" in prompt
        assert "3000-4000" in prompt

    @pytest.mark.asyncio
    async def test_report_node_fast_sets_progress_70(self):
        state = _state(mode="fast")
        state["evidence_bundle"] = {"evidence_items": []}
        captured: dict = {}

        async def fake_execute(ctx, input_data):
            captured["fast_mode"] = input_data.fast_mode
            doc = MagicMock()
            doc.model_dump.return_value = {
                "formats": {"markdown": "# Report"},
                "sections": [],
                "metadata": {},
            }
            return MagicMock(
                success=True,
                output=MagicMock(report_document=doc),
                phase_record={"phase": "reporting"},
            )

        with patch("app.infrastructure.workflow.nodes.ReportAgent") as mock_cls:
            mock_cls.return_value.aexecute = AsyncMock(side_effect=fake_execute)

            async def passthrough_wait(coro, timeout):
                return await coro

            with patch("asyncio.wait_for", side_effect=passthrough_wait):
                with patch("app.infrastructure.persistence.task_report_runtime.touch_task_progress") as touch:
                    result = await report_node(state)

        assert captured["fast_mode"] is True
        assert result["progress"] == 85.0
        touch.assert_called_once()
        assert touch.call_args.kwargs.get("progress") == 70.0
