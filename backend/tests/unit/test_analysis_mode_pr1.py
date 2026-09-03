"""PR1: analysis mode config, Tavily max_results, node timeouts, research truncation."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import PlannerInput, ResearchInput
from app.infrastructure.agents.planner_agent import PlannerAgent
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.agents.strategy_agent import StrategyAgent
from app.infrastructure.agents.report_agent import ReportAgent
from app.infrastructure.tools.research_source import EvidenceItem, SourceResult, SourceType
from app.infrastructure.tools.sources.tavily_source import TavilySource
from app.infrastructure.workflow.analysis_mode import get_mode_config
from app.infrastructure.workflow.nodes import (
    insight_node,
    plan_node,
    report_node,
    research_node,
    review_node,
    strategy_node,
)
from app.infrastructure.workflow.state import WorkflowState


def _base_state(*, mode: str = "fast") -> WorkflowState:
    return WorkflowState(
        task_id="test-pr1",
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
        research_plan={"objective": "test", "analysis_scope": ["features"]},
    )


class TestAnalysisModeConfig:
    def test_fast_defaults_include_new_fields(self):
        cfg = get_mode_config("fast")
        assert cfg.plan_timeout_s == 30.0
        assert cfg.research_timeout_s == 120.0
        assert cfg.report_timeout_s == 180.0
        assert cfg.skip_compare is True
        assert cfg.skip_evidence_evaluation is True
        assert cfg.research_max_results == 4

    def test_full_defaults_include_new_fields(self):
        cfg = get_mode_config("full")
        assert cfg.plan_timeout_s == 40.0
        assert cfg.research_timeout_s == 180.0
        assert cfg.compare_timeout_s == 90.0
        assert cfg.insight_timeout_s == 90.0
        assert cfg.strategy_timeout_s == 90.0
        assert cfg.report_timeout_s == 150.0
        assert cfg.review_timeout_s == 60.0
        assert cfg.skip_evidence_evaluation is False
        assert cfg.research_max_results == 4
        assert cfg.max_evidence_items == 15
        assert cfg.max_evaluated_items == 10
        assert cfg.mode_total_budget_s == 720.0

    def test_default_mode_is_fast(self):
        cfg = get_mode_config(None)
        assert cfg.mode == "fast"


class TestTavilyMaxResults:
    @pytest.mark.asyncio
    async def test_tavily_reads_max_results_from_context(self):
        source = TavilySource()
        captured: dict = {}

        async def fake_search(*, query, max_results, search_depth, include_raw_content):
            captured["max_results"] = max_results
            return MagicMock(error=None, status="success", items=[])

        with patch(
            "app.infrastructure.tools.sources.tavily_source.tavily_search",
            new=AsyncMock(side_effect=fake_search),
        ):
            await source.search("query", context={"max_results_per_source": 4})

        assert captured["max_results"] == 4

    @pytest.mark.asyncio
    async def test_tavily_default_when_context_missing(self):
        source = TavilySource()
        captured: dict = {}

        async def fake_search(*, query, max_results, search_depth, include_raw_content):
            captured["max_results"] = max_results
            return MagicMock(error=None, status="success", items=[])

        with patch(
            "app.infrastructure.tools.sources.tavily_source.tavily_search",
            new=AsyncMock(side_effect=fake_search),
        ):
            await source.search("query")

        assert captured["max_results"] == TavilySource.DEFAULT_MAX_RESULTS


class TestNodeTimeouts:
    @pytest.mark.asyncio
    async def test_plan_node_passes_llm_timeout_to_planner(self):
        state = _base_state()
        captured: list[float | None] = []

        async def capture_execute(ctx, input_data):
            captured.append(input_data.llm_timeout_seconds)
            mock_plan = PlannerAgent._mock_plan(input_data)
            return MagicMock(
                success=True,
                output=MagicMock(research_plan=mock_plan),
                phase_record={"phase": "planned", "status": "completed"},
            )

        with patch("app.infrastructure.workflow.nodes.PlannerAgent.aexecute", new=AsyncMock(side_effect=capture_execute)):
            result = await plan_node(state)

        assert captured == [30.0]
        assert result["current_phase"] == "planned"

    @pytest.mark.asyncio
    async def test_plan_node_timeout_falls_back_to_mock_plan(self):
        state = _base_state()

        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await plan_node(state)

        assert result["current_phase"] == "planned"
        assert result["progress"] == 15.0
        assert any("plan_timeout" in str(h.get("error", "")) for h in result["phase_history"])

    @pytest.mark.asyncio
    async def test_insight_node_timeout_returns_empty_insights(self):
        state = _base_state(mode="full")
        state["clusters"] = []
        state["gap_analysis"] = {}

        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await insight_node(state)

        assert result["current_phase"] == "insighted"
        assert result["insights"] == {}

    @pytest.mark.asyncio
    async def test_strategy_node_timeout_returns_empty_strategy(self):
        state = _base_state(mode="full")

        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await strategy_node(state)

        assert result["current_phase"] == "strategized"
        si = result["strategic_insights"]
        assert si.get("strategy_timeout") is True
        assert si.get("strategy_fallback") == "evidence_stub"

    @pytest.mark.asyncio
    async def test_report_node_timeout_uses_fallback(self):
        state = _base_state(mode="full")
        state["evidence_bundle"] = {"evidence_items": []}

        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await report_node(state)

        assert result["current_phase"] == "reported"
        doc = result["report_document"]
        assert doc["formats"]["markdown"]

    @pytest.mark.asyncio
    async def test_review_node_timeout_partial_review(self):
        state = _base_state(mode="full")
        state["report_document"] = {
            "formats": {"markdown": "# Report\n\nContent"},
        }

        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await review_node(state)

        assert result["current_phase"] == "reviewed"
        assert result["review_result"]["passed_for_output"] is True
        assert result["review_result"].get("timeout_partial") is True


class TestAgentLlmTimeouts:
    def test_strategy_agent_source_has_no_900_hardcode(self):
        import inspect
        source = inspect.getsource(StrategyAgent.arun)
        assert "900.0" not in source

    def test_report_agent_source_has_no_1200_hardcode(self):
        import inspect
        source = inspect.getsource(ReportAgent.arun)
        assert "1200.0" not in source


class TestResearchFastMode:
    @pytest.mark.asyncio
    async def test_fast_mode_skips_evidence_evaluator(self):
        from app.infrastructure.agents.research_prompt import ExtractedEvidence, EvidenceItem as PromptEvidenceItem

        agent = ResearchAgent()
        input_data = ResearchInput(
            skip_evidence_evaluation=True,
            max_results_per_source=4,
        )
        results = [
            SourceResult(
                items=[
                    EvidenceItem(
                        source_type=SourceType.WEB,
                        source_name="T",
                        title="t",
                        url="https://example.com/1",
                        content="content body",
                    )
                ],
                source_type=SourceType.WEB,
                source_name="T",
                status="success",
                total_found=1,
            )
        ]
        parsed = ExtractedEvidence(
            evidence_items=[
                PromptEvidenceItem(
                    title="t",
                    source="T",
                    url="https://example.com/1",
                    summary="s",
                    confidence="medium",
                    dimension="features",
                    date="",
                )
            ]
        )

        with patch(
            "app.infrastructure.agents.research_agent.llm_client.generate",
            new=AsyncMock(return_value=MagicMock(parsed=parsed, content="")),
        ):
            with patch(
                "app.infrastructure.tools.evidence_evaluator.evidence_evaluator.evaluate_batch",
                new=AsyncMock(),
            ) as mock_eval:
                deduped, summary = await agent._extract_evidence_from_sources(
                    "objective",
                    results,
                    input_data,
                    4,
                    lambda: 999.0,
                )

        mock_eval.assert_not_called()
        assert "evidence_evaluation_skipped" in summary
        assert len(deduped) == 1

    @pytest.mark.asyncio
    async def test_research_node_timeout_returns_partial_evidence_at_40(self):
        state = _base_state()
        partial = MagicMock()
        partial.success = True
        partial.output.evidence_bundle = __import__(
            "app.application.dto.agent_dto", fromlist=["EvidenceBundleDTO"]
        ).EvidenceBundleDTO(
            evidence_items=[
                __import__(
                    "app.application.dto.agent_dto", fromlist=["EvidenceItemDTO"]
                ).EvidenceItemDTO(
                    id="E001",
                    title="t",
                    source="T",
                    url="https://example.com/1",
                    content="c",
                )
            ]
        )
        partial.output.quality_report = __import__(
            "app.application.dto.agent_dto", fromlist=["QualityReport"]
        ).QualityReport()
        partial.phase_record = {"phase": "researched", "status": "completed", "evidence_count": 1}

        mock_agent = MagicMock()
        mock_agent.aexecute = AsyncMock(side_effect=asyncio.TimeoutError)
        mock_agent.build_partial_result = AsyncMock(return_value=partial)

        with patch("app.infrastructure.workflow.nodes.ResearchAgent", return_value=mock_agent):
            with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
                result = await research_node(state)

        assert result["progress"] == 40.0
        assert result["current_phase"] == "researched"
        assert len(result["evidence_bundle"]["evidence_items"]) == 1

    @pytest.mark.asyncio
    async def test_cancelled_error_propagates_from_base_agent(self):
        agent = ResearchAgent()

        async def cancelled_run(ctx, input_data):
            raise asyncio.CancelledError()

        with patch.object(agent, "arun", new=cancelled_run):
            with pytest.raises(asyncio.CancelledError):
                await agent.aexecute(
                    __import__("app.infrastructure.agents.base", fromlist=["AgentContext"]).AgentContext(
                        task_id="t", current_phase="researching"
                    ),
                    ResearchInput(),
                )
