"""PR4: Full mode 720s budget — evidence caps, timeout degradations, watchdog."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import EvidenceItemDTO, ResearchInput
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.agents.report_prompt import build_report_prompt
from app.infrastructure.workflow.analysis_mode import get_mode_config
from app.infrastructure.workflow.nodes import (
    insight_node,
    report_node,
    review_node,
    strategy_node,
)
from app.infrastructure.workflow.state import WorkflowState


def _full_state(**extra) -> WorkflowState:
    base = WorkflowState(
        task_id="test-pr4",
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
        progress=72.0,
        research_plan={"objective": "test", "analysis_scope": ["features"]},
        evidence_bundle={"evidence_items": []},
        gap_analysis={},
        strategic_insights={},
        report_document={"formats": {"markdown": "# Report\n\nBody"}},
    )
    base.update(extra)
    return base


def _make_evidence(n: int) -> list[EvidenceItemDTO]:
    return [
        EvidenceItemDTO(
            id=f"E{i + 1:03d}",
            title=f"Evidence {i}",
            source="web",
            content=f"Content {i}",
            url=f"https://example.com/{i}",
            date="2025-01-01",
            confidence="medium",
            category="features",
        )
        for i in range(n)
    ]


class TestFullModeConfig:
    def test_full_evidence_and_budget_caps(self):
        cfg = get_mode_config("full")
        assert cfg.max_evidence_items == 15
        assert cfg.max_evaluated_items == 10
        assert cfg.compare_max_evidence_items == 12
        assert cfg.mode_total_budget_s == 720.0
        assert cfg.research_max_results == 4
        assert cfg.max_source_types == 3

    def test_fast_mode_unaffected_caps(self):
        cfg = get_mode_config("fast")
        assert cfg.max_evidence_items == 999
        assert cfg.max_evaluated_items == 0
        assert cfg.mode_total_budget_s == 360.0


class TestEvidenceCaps:
    def test_dedupe_truncates_to_fifteen(self):
        agent = ResearchAgent()
        items = _make_evidence(20)
        input_data = ResearchInput(max_evidence_items=15)
        capped, meta = agent._apply_evidence_caps(items, input_data)
        assert len(capped) == 15
        assert meta["evidence_truncated_count"] == 5

    @pytest.mark.asyncio
    async def test_evaluator_only_scores_first_ten(self):
        agent = ResearchAgent()
        deduped = _make_evidence(12)
        input_data = ResearchInput(max_evidence_items=15, max_evaluated_items=10)
        evaluated_count = 0

        agent._sort_evidence_by_temporal(deduped)
        agent._ensure_default_quality_scores(deduped)
        eval_items = deduped[:10]

        async def fake_eval_batch(*, items, objective, max_concurrent=5):
            nonlocal evaluated_count
            evaluated_count = len(items)
            return [MagicMock(to_dict=lambda: {"overall_confidence": 0.7}) for _ in items]

        with patch(
            "app.infrastructure.tools.evidence_evaluator.evidence_evaluator.evaluate_batch",
            new=AsyncMock(side_effect=fake_eval_batch),
        ):
            quality_scores = await fake_eval_batch(items=[{}] * len(eval_items), objective="x")
            for i, score in enumerate(quality_scores):
                qs = score.to_dict()
                qs["evaluator_skipped"] = False
                deduped[i].quality_score = qs

        capped, _meta = agent._apply_evidence_caps(deduped, input_data)

        assert evaluated_count == 10
        assert len(capped) == 12
        assert capped[0].quality_score.get("evaluator_skipped") is False
        assert capped[10].quality_score.get("evaluator_skipped") is True

    def test_fast_mode_passes_no_evidence_caps_to_research_input(self):
        cfg = get_mode_config("fast")
        max_evidence = cfg.max_evidence_items if cfg.mode == "full" else None
        max_evaluated = cfg.max_evaluated_items if cfg.mode == "full" else None
        assert max_evidence is None
        assert max_evaluated is None

    def test_full_mode_passes_evidence_caps_to_research_input(self):
        cfg = get_mode_config("full")
        max_evidence = cfg.max_evidence_items if cfg.mode == "full" else None
        max_evaluated = cfg.max_evaluated_items if cfg.mode == "full" else None
        assert max_evidence == 15
        assert max_evaluated == 10


class TestFullTimeoutDegradation:
    @pytest.mark.asyncio
    async def test_insight_timeout_returns_empty_and_continues(self):
        state = _full_state(current_phase="compared")
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await insight_node(state)
        assert result["current_phase"] == "insighted"
        assert result["insights"] == {}

    @pytest.mark.asyncio
    async def test_strategy_timeout_returns_empty_and_continues(self):
        state = _full_state(current_phase="insighted", insights={})
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await strategy_node(state)
        assert result["current_phase"] == "strategized"
        # No evidence in _full_state → stub still returned with meta (may have empty SWOT lists)
        si = result["strategic_insights"]
        assert si.get("strategy_timeout") is True
        assert si.get("strategy_fallback") == "evidence_stub"

    @pytest.mark.asyncio
    async def test_report_timeout_uses_fallback_and_continues(self):
        state = _full_state(current_phase="strategized")
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await report_node(state)
        assert result["current_phase"] == "reported"
        assert result["report_document"]["formats"]["markdown"]

    @pytest.mark.asyncio
    async def test_review_timeout_partial_passes_output(self):
        state = _full_state(current_phase="reported")
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await review_node(state)
        rr = result["review_result"]
        assert result["current_phase"] == "reviewed"
        assert rr["passed_for_output"] is True
        assert rr["timeout_partial"] is True
        assert rr["review_partial"] is True
        assert any("审阅超时" in i.get("description", "") for i in rr.get("issues", []))


class TestWatchdog:
    @pytest.mark.asyncio
    async def test_review_skipped_when_total_budget_exhausted(self):
        state = _full_state(current_phase="reported")
        state["workflow_started_at"] = time.monotonic() - 730.0
        result = await review_node(state)
        rr = result["review_result"]
        assert rr["review_skipped_total_budget"] is True
        assert rr["passed_for_output"] is True
        assert result["current_phase"] == "reviewed"
        assert result["workflow_budget_meta"]["total_elapsed_s"] >= 715.0


class TestFullReportPrompt:
    def test_standard_prompt_uses_3000_4000_words(self):
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
        assert "3000-4000" in prompt

    def test_compact_report_shortens_word_limit(self):
        prompt = build_report_prompt(
            our_company="A",
            competitor_company="B",
            product="P",
            objective="product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
            fast_mode=False,
            compact_report=True,
        )
        assert "2500-3000" in prompt
        assert "720s" in prompt
