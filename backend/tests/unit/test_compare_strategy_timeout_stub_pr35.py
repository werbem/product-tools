"""Step 35: Compare / Strategy timeout partial + evidence stub."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.application.dto.agent_dto import CompareInput, InsightInput, StrategyInput
from app.infrastructure.agents.compare_agent import CompareAgent
from app.infrastructure.agents.insight_agent import InsightAgent
from app.infrastructure.agents.report_agent import ReportAgent
from app.infrastructure.agents.report_prompt import build_report_prompt
from app.infrastructure.agents.strategy_agent import StrategyAgent
from app.infrastructure.agents.timeout_stubs import (
    build_compare_stub_from_evidence,
    build_strategy_stub_from_evidence,
    try_parse_compare_llm_json,
)
from app.infrastructure.workflow.nodes import compare_node, strategy_node
from app.infrastructure.workflow.progress_hints import (
    COMPARE_TIMEOUT_STUB_HINT,
    STRATEGY_TIMEOUT_STUB_HINT,
)
from app.infrastructure.workflow.state import WorkflowState
from app.infrastructure.workflow.workflow_budget import COMPARE_BUDGET_ELAPSED_S


def _evidence_items(n: int = 3) -> list[dict]:
    return [
        {
            "id": f"E{i + 1:03d}",
            "title": f"飞猪 vs 美团 evidence {i}",
            "content": f"Content about 飞猪 and 美团 item {i}",
            "url": f"https://example.com/{i}",
            "source": "web",
            "category": "growth",
            "confidence": "medium",
            "quality_score": {"temporal_level": "unknown"},
        }
        for i in range(n)
    ]


def _full_state(**extra) -> WorkflowState:
    base = WorkflowState(
        task_id="test-pr35",
        user_input={
            "our_company": "飞猪",
            "competitor_company": "美团",
            "product": "酒店",
            "objective": "product_improvement",
            "optional": {"analysis_mode": "full"},
        },
        validated_input={
            "our_company": "飞猪",
            "competitor_company": "美团",
            "product": "酒店",
            "objective": "product_improvement",
        },
        current_phase="researched",
        phase_history=[],
        errors=[],
        progress=40.0,
        research_plan={"objective": "test", "analysis_scope": ["growth"]},
        evidence_bundle={"evidence_items": _evidence_items()},
        clusters=[],
        gap_analysis={},
        insights={},
        strategic_insights={},
        workflow_budget_meta={},
    )
    base.update(extra)
    return base


class TestCompareTimeoutStub:
    def test_stub_from_evidence_nonempty(self):
        stub = build_compare_stub_from_evidence(
            {"evidence_items": _evidence_items(4)},
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
        )
        assert stub["compare_fallback"] == "evidence_stub"
        assert stub["compare_timeout"] is True
        assert stub["gaps"]["capability_gaps"]
        assert len(stub["features"]["feature_matrix"]) <= 12

    def test_stub_no_evidence_still_has_meta(self):
        stub = build_compare_stub_from_evidence({"evidence_items": []})
        assert stub["compare_fallback"] == "evidence_stub"
        assert stub["gaps"]["capability_gaps"] == []

    def test_partial_json_preferred_over_stub(self):
        agent = CompareAgent()
        agent._partial_input = CompareInput(
            evidence_bundle={"evidence_items": _evidence_items()},
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
        )
        agent._partial_raw_text = """{
          "differences": [{
            "dimension": "growth",
            "title": "用户下降",
            "our_status": "下降",
            "competitor_status": "上升",
            "evidence_refs": ["E001"],
            "user_impact": "x",
            "business_impact": "y",
            "confidence": "high"
          }],
          "advantages": [],
          "disadvantages": [],
          "capability_gaps": [],
          "dimensions_analyzed": ["growth"],
          "dimensions_skipped": [],
          "overall_summary": "partial ok"
        }"""
        result = agent.build_partial_result()
        assert result.success
        meta = result.phase_record
        assert meta["compare_fallback"] == "partial_json"
        assert meta["compare_partial"] is True
        gap = meta["gap_dict"]
        assert gap["features"]["feature_matrix"]
        assert gap["compare_fallback"] == "partial_json"

    @pytest.mark.asyncio
    async def test_compare_node_timeout_with_evidence_returns_stub(self):
        state = _full_state()
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await compare_node(state)
        assert result["current_phase"] == "compared"
        gap = result["gap_analysis"]
        assert gap.get("compare_fallback") == "evidence_stub"
        assert gap.get("gaps", {}).get("capability_gaps")
        assert result.get("stage_hint") == COMPARE_TIMEOUT_STUB_HINT
        assert any("compare_timeout" in str(h.get("error", "")) for h in result["phase_history"])


class TestStrategyTimeoutStub:
    def test_stub_has_swot_and_recs(self):
        stub = build_strategy_stub_from_evidence(
            {"evidence_items": _evidence_items(5)},
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="增长分析",
        )
        assert stub["strategy_fallback"] == "evidence_stub"
        assert stub["swot_source"] == "evidence_stub"
        assert stub["swot"]["strengths"] or stub["swot"]["weaknesses"] or stub["swot"]["threats"]
        assert 1 <= len(stub["recommendations"]) <= 3

    @pytest.mark.asyncio
    async def test_strategy_node_timeout_with_evidence_returns_stub(self):
        state = _full_state(current_phase="insighted")
        with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
            result = await strategy_node(state)
        assert result["current_phase"] == "strategized"
        si = result["strategic_insights"]
        assert si.get("strategy_fallback") == "evidence_stub"
        assert si.get("swot_source") == "evidence_stub"
        assert si.get("swot")
        assert result.get("stage_hint") == STRATEGY_TIMEOUT_STUB_HINT

    def test_strategy_partial_json_preferred(self):
        agent = StrategyAgent()
        agent._partial_input = StrategyInput(
            evidence_bundle={"evidence_items": _evidence_items()},
            gap_analysis={},
            product="酒店",
            objective="test",
            our_company="飞猪",
            competitor_company="美团",
        )
        agent._partial_raw_text = """{
          "swot": {
            "strengths": [{"conclusion": "生态流量", "evidence_refs": ["E001"], "confidence": "medium"}],
            "weaknesses": [],
            "opportunities": [],
            "threats": []
          },
          "opportunities": [],
          "risks": [],
          "recommendations": [{"action": "加深供应链", "rationale": "r", "priority": "p1",
            "timeline": "short_term", "evidence_refs": ["E001"], "expected_value": "x"}],
          "roadmap": {"short_term": [], "medium_term": [], "long_term": []},
          "overall_confidence": "medium"
        }"""
        result = agent.build_partial_result()
        assert result.phase_record["strategy_fallback"] == "partial_json"
        assert result.phase_record["swot_source"] == "partial_json"
        si = result.phase_record["strategy_dict"]
        assert si["swot"]["strengths"]


class TestReportConsumesStub:
    def test_prompt_forbids_second_swot_when_stub(self):
        prompt = build_report_prompt(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="product_improvement",
            evidence_json="[]",
            gap_json='{"compare_fallback":"evidence_stub"}',
            strategy_json='{"swot_source":"evidence_stub","swot":{"strengths":[]}}',
            fast_mode=False,
            strategy_is_stub=True,
            gap_is_stub=True,
        )
        assert "evidence_stub" in prompt
        assert "禁止" in prompt and "参考性" in prompt
        assert "保持 Strategy 结论不变" not in prompt

    def test_serialize_preserves_swot_source(self):
        payload = ReportAgent._serialize_strategy({
            "swot": {"strengths": [{"item": "s", "evidence_refs": ["E001"]}],
                     "weaknesses": [], "opportunities": [], "threats": []},
            "recommendations": [],
            "opportunities": [],
            "risks": [],
            "roadmap": {"phases": []},
            "swot_source": "evidence_stub",
            "strategy_fallback": "evidence_stub",
        })
        assert "evidence_stub" in payload
        assert "swot_source" in payload


class TestInsightFlatEvidence:
    @pytest.mark.asyncio
    async def test_empty_gap_with_evidence_does_not_early_exit(self):
        agent = InsightAgent()
        called = {}

        async def fake_generate(**kwargs):
            called["prompt"] = kwargs.get("user_prompt", "")
            from types import SimpleNamespace
            return SimpleNamespace(content='{"insights":[],"summary":"ok"}')

        with patch("app.infrastructure.agents.insight_agent.llm_client.generate", new=fake_generate):
            result = await agent.arun(
                None,  # type: ignore[arg-type]
                InsightInput(
                    evidence_clusters=[],
                    gap_analysis={},
                    flat_evidence_items=_evidence_items(),
                    our_company="飞猪",
                    competitor_company="美团",
                    product="酒店",
                    objective="test",
                ),
            )
        assert result.success
        assert result.phase_record.get("insight_flat_evidence") is True
        assert result.phase_record.get("insight_skipped_empty_gap") is False
        assert "扁平证据" in called["prompt"]

    @pytest.mark.asyncio
    async def test_no_evidence_still_early_exit(self):
        agent = InsightAgent()
        result = await agent.arun(
            None,  # type: ignore[arg-type]
            InsightInput(
                evidence_clusters=[],
                gap_analysis={},
                flat_evidence_items=[],
                our_company="飞猪",
                competitor_company="美团",
                product="酒店",
            ),
        )
        assert result.output.summary == "证据不足，无法生成洞察"
        assert result.phase_record.get("insight_skipped_empty_gap") is True


class TestBudgetSkipUnchanged:
    @pytest.mark.asyncio
    async def test_compare_budget_skip_still_empty(self):
        import time

        state = _full_state()
        state["workflow_started_at"] = time.monotonic() - (COMPARE_BUDGET_ELAPSED_S + 5)
        result = await compare_node(state)
        assert result["current_phase"] == "compared"
        assert result.get("workflow_budget_meta", {}).get("compare_skipped_budget") is True


class TestParseHelpers:
    def test_try_parse_compare(self):
        parsed = try_parse_compare_llm_json(
            '{"differences":[{"dimension":"a","title":"t","our_status":"o",'
            '"competitor_status":"c","evidence_refs":["E001"]}],'
            '"capability_gaps":[],"advantages":[],"disadvantages":[]}'
        )
        assert parsed is not None
        assert parsed.differences
