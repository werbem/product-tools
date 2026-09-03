"""Step 40: Compare/Strategy compact completion rate (FakeLLM, no slow calls)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import CompareInput, StrategyInput
from app.infrastructure.agents.agent_io_compact import compress_evidence_items
from app.infrastructure.agents.compare_agent import CompareAgent
from app.infrastructure.agents.strategy_agent import StrategyAgent
from app.infrastructure.agents.base import AgentContext
from app.infrastructure.workflow.analysis_mode import resolve_mode_config
from app.infrastructure.workflow.nodes import compare_node, strategy_node
from app.infrastructure.workflow.state import WorkflowState
from app.infrastructure.workflow.workflow_budget import (
    effective_compare_timeout_s,
    effective_strategy_timeout_s,
    split_primary_repair_timeouts,
)


def _evidence(n: int = 10) -> list[dict]:
    return [
        {
            "id": f"E{i + 1:03d}",
            "title": f"title {i}",
            "content": ("snippet body " * 40) + f" item {i}",
            "url": f"https://ex.com/{i}",
            "source": "web",
            "category": "business" if i % 2 else "growth",
            "confidence": "medium",
            "quality_score": {"temporal_level": "recent" if i < 3 else "aging"},
        }
        for i in range(n)
    ]


def _full_state(**extra) -> WorkflowState:
    base = WorkflowState(
        task_id="test-pr40",
        user_input={
            "our_company": "龙腾出行",
            "competitor_company": "悦途",
            "product": "机场场景",
            "objective": "product_improvement",
            "optional": {"analysis_mode": "full"},
        },
        validated_input={
            "our_company": "龙腾出行",
            "competitor_company": "悦途",
            "product": "机场场景",
            "objective": "product_improvement",
        },
        current_phase="researched",
        phase_history=[],
        errors=[],
        progress=40.0,
        research_plan={"objective": "test", "analysis_scope": ["business", "growth"]},
        evidence_bundle={"evidence_items": _evidence(12)},
        clusters=[],
        gap_analysis={},
        insights={},
        strategic_insights={},
        workflow_budget_meta={},
        workflow_started_at=None,
    )
    base.update(extra)
    return base


COMPARE_JSON = """{
  "differences": [
    {"dimension":"business","title":"贵宾厅网络","our_status":"全球覆盖广","competitor_status":"区域深耕","evidence_refs":["E001"],"user_impact":"选择更多","business_impact":"规模优势","confidence":"medium"}
  ],
  "capability_gaps": [
    {"dimension":"growth","title":"海外扩张","our_status":"布局早","competitor_status":"追赶中","evidence_refs":["E003"],"user_impact":"跨境体验","business_impact":"增长","confidence":"medium"}
  ],
  "advantages": ["网络"],
  "disadvantages": ["本地化"],
  "dimensions_analyzed": ["business"],
  "dimensions_skipped": [],
  "overall_summary": "网络广度差异明显"
}"""

STRATEGY_JSON = """{
  "swot": {
    "strengths": [{"conclusion":"网络覆盖广","evidence_refs":["E001"],"confidence":"medium"}],
    "weaknesses": [{"conclusion":"本地运营弱","evidence_refs":["E002"],"confidence":"low"}],
    "opportunities": [{"conclusion":"海外协同","evidence_refs":["E003"],"confidence":"medium"}],
    "threats": [{"conclusion":"竞品深耕","evidence_refs":["E004"],"confidence":"medium"}]
  },
  "recommendations": [
    {"action":"强化海外联营","rationale":"对标竞品差异","priority":"p1","evidence_refs":["E003"]}
  ],
  "overall_confidence": "medium"
}"""


class TestBudgetHelpers:
    def test_split_primary_repair(self):
        primary, repair = split_primary_repair_timeouts(90)
        assert primary + repair == pytest.approx(90, abs=0.01)
        assert primary > repair
        assert repair >= 8

    def test_tight_remaining_uses_shorter_compare_budget(self):
        import time

        # ~500s elapsed → remaining ~220; after full reserve goes tight → ≤60s
        state = _full_state(workflow_started_at=time.monotonic() - 500.0)
        cfg = resolve_mode_config(state)
        t = effective_compare_timeout_s(state, cfg)
        assert 0 < t <= 60

    def test_strategy_reserve_leaves_report_room(self):
        import time

        state = _full_state(workflow_started_at=time.monotonic() - 500.0)
        cfg = resolve_mode_config(state)
        t = effective_strategy_timeout_s(state, cfg)
        assert t <= cfg.strategy_timeout_s
        assert t > 0


class TestEvidenceCompress:
    def test_cap_and_snippet(self):
        items = compress_evidence_items(_evidence(20), cap=8, snippet_chars=250)
        assert len(items) == 8
        assert all(len(i["summary"]) <= 250 for i in items)
        assert items[0]["id"]


class TestCompareCompactAgent:
    @pytest.mark.asyncio
    async def test_fast_fake_llm_compact_agent_not_stub(self):
        agent = CompareAgent()
        fake = MagicMock()
        fake.content = COMPARE_JSON
        fake.parsed = None

        with patch(
            "app.infrastructure.agents.compare_agent.llm_client.generate",
            new=AsyncMock(return_value=fake),
        ) as gen:
            result = await agent.arun(
                AgentContext(task_id="t", current_phase="comparing"),
                CompareInput(
                    evidence_bundle={"evidence_items": _evidence(12)},
                    our_company="龙腾出行",
                    competitor_company="悦途",
                    product="机场场景",
                    analysis_scope=["business"],
                    llm_timeout_seconds=90,
                    compact=True,
                ),
            )
        assert result.success
        assert result.phase_record.get("compare_mode") == "compact_agent"
        assert result.output.gap_analysis.features
        assert "非完整" not in str(result.output.gap_analysis.model_dump())
        # primary call only (no repair needed)
        assert gen.await_count == 1
        # compressed prompt (no huge indent dumps)
        user_prompt = gen.await_args.kwargs.get("user_prompt") or gen.await_args.args[1]
        assert "compact" in user_prompt.lower() or "≤" in user_prompt or "上限" in user_prompt

    @pytest.mark.asyncio
    async def test_bad_json_then_repair_succeeds(self):
        agent = CompareAgent()
        bad = MagicMock(content="{not json", parsed=None)
        good = MagicMock(content=COMPARE_JSON, parsed=None)
        gen = AsyncMock(side_effect=[bad, good])
        with patch("app.infrastructure.agents.compare_agent.llm_client.generate", new=gen):
            result = await agent.arun(
                AgentContext(task_id="t", current_phase="comparing"),
                CompareInput(
                    evidence_bundle={"evidence_items": _evidence(8)},
                    our_company="A",
                    competitor_company="B",
                    product="P",
                    llm_timeout_seconds=90,
                    compact=True,
                ),
            )
        assert result.phase_record.get("compare_mode") == "compact_agent"
        assert gen.await_count == 2

    @pytest.mark.asyncio
    async def test_timeout_still_stub(self):
        state = _full_state()
        with patch(
            "app.infrastructure.agents.compare_agent.CompareAgent.aexecute",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            # Force wait_for timeout by patching wait_for
            async def _boom(*a, **k):
                raise asyncio.TimeoutError()

            with patch("asyncio.wait_for", new=_boom):
                out = await compare_node(state)
        assert out["current_phase"] == "compared"
        gap = out.get("gap_analysis") or {}
        assert gap.get("compare_fallback") == "evidence_stub" or (
            out.get("workflow_budget_meta") or {}
        ).get("compare_fallback") == "evidence_stub"
        assert "非完整" in str(gap.get("generation_note") or gap.get("positioning") or "")


class TestStrategyCompactAgent:
    @pytest.mark.asyncio
    async def test_fast_fake_llm_strategy_compact(self):
        agent = StrategyAgent()
        fake = MagicMock(content=STRATEGY_JSON, parsed=None)
        with patch(
            "app.infrastructure.agents.strategy_agent.llm_client.generate",
            new=AsyncMock(return_value=fake),
        ):
            result = await agent.arun(
                AgentContext(task_id="t", current_phase="strategizing"),
                StrategyInput(
                    evidence_bundle={"evidence_items": _evidence(10)},
                    gap_analysis={"features": {"feature_matrix": []}},
                    objective="竞品差异",
                    product="机场",
                    our_company="龙腾",
                    competitor_company="悦途",
                    llm_timeout_seconds=90,
                    compact=True,
                ),
            )
        assert result.success
        assert result.phase_record.get("strategy_mode") == "compact_agent"
        swot = result.output.strategic_insights.swot
        assert swot.strengths


class TestFastSkipRegression:
    @pytest.mark.asyncio
    async def test_fast_skips_compare(self):
        state = _full_state()
        state["user_input"]["optional"] = {"analysis_mode": "fast"}
        cfg = resolve_mode_config(state)
        assert cfg.skip_compare is True
