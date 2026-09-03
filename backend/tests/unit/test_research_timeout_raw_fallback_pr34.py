"""Step 34: Research timeout raw → evidence fallback."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import (
    EvidenceBundleDTO,
    EvidenceItemDTO,
    ResearchInput,
)
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.tools.research_source import EvidenceItem, SourceResult, SourceType
from app.infrastructure.workflow.nodes import research_node
from app.infrastructure.workflow.progress_hints import (
    NO_EVIDENCE_CLUSTERING_HINT,
    RAW_TIMEOUT_FALLBACK_HINT,
)
from app.infrastructure.workflow.state import WorkflowState


def _raw_source(
    *,
    n: int = 2,
    source_name: str = "Tavily",
    status: str = "success",
    error: str | None = None,
) -> SourceResult:
    items = [
        EvidenceItem(
            source_type=SourceType.WEB,
            source_name=source_name,
            title=f"{source_name} title {i}",
            url=f"https://example.com/{source_name}/{i}",
            content=f"snippet body for {source_name} item {i} " * 5,
            published_date="2024-06-01",
        )
        for i in range(n)
    ]
    return SourceResult(
        items=[] if error else items,
        source_type=SourceType.WEB,
        source_name=source_name,
        status="error" if error else status,
        error=error,
        total_found=0 if error else n,
    )


def _full_state() -> WorkflowState:
    return WorkflowState(
        task_id="test-pr34",
        user_input={
            "our_company": "飞猪",
            "competitor_company": "美团、携程",
            "product": "酒店",
            "objective": "product_improvement",
            "optional": {"analysis_mode": "full"},
        },
        validated_input={
            "our_company": "飞猪",
            "competitor_company": "美团、携程",
            "product": "酒店",
            "objective": "product_improvement",
        },
        current_phase="planned",
        phase_history=[],
        errors=[],
        progress=15.0,
        research_plan={"objective": "test", "analysis_scope": ["growth"]},
        workflow_budget_meta={},
    )


class TestRawTimeoutFallback:
    def test_build_partial_converts_raw_when_extract_empty(self):
        agent = ResearchAgent()
        input_data = ResearchInput(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            max_evidence_items=15,
            max_results_per_source=4,
            enable_lightweight_date_enrichment=False,
        )
        agent._partial_input_data = input_data
        agent._partial_all_results = [_raw_source(n=3), _raw_source(n=2, source_name="News")]
        agent._partial_evidence_items = []

        partial = asyncio.run(agent.build_partial_result())
        assert partial is not None
        assert partial.success
        items = partial.output.evidence_bundle.evidence_items
        assert len(items) > 0
        assert all(e.url for e in items)
        assert all(
            (e.raw_data or {}).get("extraction_method") == "raw_timeout_fallback"
            for e in items
        )
        assert all(e.confidence == "low" for e in items)
        qr = partial.output.quality_report
        assert qr.research_timeout is True
        assert qr.evidence_fallback == "raw_search"
        assert qr.raw_items_converted == len(items)
        assert qr.fallback_used is True
        assert partial.phase_record.get("evidence_fallback") == "raw_search"
        assert partial.phase_record.get("sources_succeeded") == 2

    def test_build_partial_keeps_extracted_and_tops_up_raw(self):
        agent = ResearchAgent()
        input_data = ResearchInput(
            max_evidence_items=15,
            max_results_per_source=4,
            enable_lightweight_date_enrichment=False,
        )
        agent._partial_input_data = input_data
        agent._partial_all_results = [_raw_source(n=3, source_name="Tavily")]
        agent._partial_evidence_items = [
            EvidenceItemDTO(
                id="E001",
                title="already extracted",
                source="LLM",
                url="https://example.com/Tavily/0",
                content="llm summary",
                confidence="high",
            )
        ]

        partial = asyncio.run(agent.build_partial_result())
        items = partial.output.evidence_bundle.evidence_items
        urls = [e.url for e in items]
        assert "https://example.com/Tavily/0" in urls
        assert urls.count("https://example.com/Tavily/0") == 1
        assert "https://example.com/Tavily/1" in urls
        assert "https://example.com/Tavily/2" in urls
        extracted = next(e for e in items if e.title == "already extracted")
        assert extracted.confidence == "high"
        assert partial.phase_record.get("raw_items_converted", 0) >= 1

    def test_build_partial_empty_when_no_raw_and_no_evidence(self):
        agent = ResearchAgent()
        agent._partial_input_data = ResearchInput(enable_lightweight_date_enrichment=False)
        agent._partial_all_results = [
            _raw_source(n=0, error="network down"),
            SourceResult(items=[], source_name="X", status="error", error="fail"),
        ]
        agent._partial_evidence_items = []

        partial = asyncio.run(agent.build_partial_result())
        assert partial is not None
        assert partial.output.evidence_bundle.evidence_items == []
        assert partial.output.quality_report.evidence_fallback is None
        assert partial.output.quality_report.raw_items_converted == 0
        assert partial.output.quality_report.research_timeout is True

    def test_full_evidence_cap_applied_on_raw_fallback(self):
        agent = ResearchAgent()
        input_data = ResearchInput(
            max_evidence_items=15,
            max_results_per_source=10,
            enable_lightweight_date_enrichment=False,
        )
        agent._partial_input_data = input_data
        agent._partial_all_results = [
            _raw_source(n=10, source_name=f"S{i}") for i in range(3)
        ]
        agent._partial_evidence_items = []

        partial = asyncio.run(agent.build_partial_result())
        items = partial.output.evidence_bundle.evidence_items
        assert len(items) == 15
        assert partial.output.quality_report.raw_items_converted == 15

    def test_convert_marks_extraction_method(self):
        agent = ResearchAgent()
        input_data = ResearchInput(max_evidence_items=15, max_results_per_source=4)
        items, n = agent._convert_raw_results_to_evidence(
            [_raw_source(n=2)],
            input_data,
            mark_timeout_fallback=True,
        )
        assert n == 2
        assert items[0].raw_data["extraction_method"] == "raw_timeout_fallback"
        assert items[0].quality_score["reliability_score"] == 0.3


class TestResearchNodeTimeoutFallback:
    @pytest.mark.asyncio
    async def test_timeout_with_raw_partial_returns_nonempty_evidence(self):
        state = _full_state()
        agent = ResearchAgent()
        agent._partial_input_data = ResearchInput(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            max_evidence_items=15,
            max_results_per_source=4,
            skip_evidence_evaluation=True,
        )
        agent._partial_all_results = [_raw_source(n=4)]
        agent._partial_evidence_items = []

        with patch("app.infrastructure.workflow.nodes.ResearchAgent", return_value=agent):
            with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
                with patch(
                    "app.infrastructure.workflow.nodes._run_full_evidence_clustering",
                    new=AsyncMock(return_value=([], {})),
                ):
                    result = await research_node(state)

        items = result["evidence_bundle"]["evidence_items"]
        assert len(items) > 0
        assert all(i.get("url") for i in items)
        qr = result["quality_report"]
        assert qr["evidence_fallback"] == "raw_search"
        assert qr["research_timeout"] is True
        assert result["workflow_budget_meta"]["evidence_fallback"] == "raw_search"
        assert result["stage_hint"] in (
            RAW_TIMEOUT_FALLBACK_HINT,
            "证据整理完成",
            NO_EVIDENCE_CLUSTERING_HINT,
        )

    @pytest.mark.asyncio
    async def test_timeout_with_no_raw_keeps_empty_and_no_fake_evidence(self):
        state = _full_state()
        agent = ResearchAgent()
        agent._partial_input_data = ResearchInput(max_evidence_items=15)
        agent._partial_all_results = []
        agent._partial_evidence_items = []

        with patch("app.infrastructure.workflow.nodes.ResearchAgent", return_value=agent):
            with patch("asyncio.wait_for", new=AsyncMock(side_effect=asyncio.TimeoutError)):
                result = await research_node(state)

        assert result["evidence_bundle"]["evidence_items"] == []
        assert result["stage_hint"] == NO_EVIDENCE_CLUSTERING_HINT
        assert result["workflow_budget_meta"].get("clustering_skipped_no_evidence") is True

    @pytest.mark.asyncio
    async def test_compare_accepts_raw_fallback_evidence(self):
        from app.infrastructure.workflow.nodes import compare_node

        state = _full_state()
        state["evidence_bundle"] = EvidenceBundleDTO(
            evidence_items=[
                EvidenceItemDTO(
                    id="E001",
                    title="raw hit",
                    source="Tavily",
                    source_type="web",
                    url="https://example.com/1",
                    content="snippet",
                    confidence="low",
                    raw_data={"extraction_method": "raw_timeout_fallback"},
                    quality_score={"reliability_score": 0.3, "overall_confidence": 0.3},
                )
            ]
        ).model_dump()
        state["progress"] = 40.0

        fake_gap = MagicMock()
        fake_gap.model_dump.return_value = {"features": [], "gaps": []}
        fake_result = MagicMock()
        fake_result.success = True
        fake_result.output.gap_analysis = fake_gap
        fake_result.phase_record = {"phase": "compared", "status": "completed"}

        mock_agent = MagicMock()
        mock_agent.aexecute = AsyncMock(return_value=fake_result)

        with patch("app.infrastructure.workflow.nodes.CompareAgent", return_value=mock_agent):
            async def _run(coro, timeout=None):
                return await coro

            with patch("asyncio.wait_for", side_effect=_run):
                out = await compare_node(state)

        assert out["current_phase"] == "compared"
        assert mock_agent.aexecute.await_count == 1
        cmp_input = mock_agent.aexecute.await_args.args[1]
        assert len(cmp_input.evidence_bundle.get("evidence_items") or []) == 1
        assert (
            cmp_input.evidence_bundle["evidence_items"][0]["raw_data"]["extraction_method"]
            == "raw_timeout_fallback"
        )


class TestExtractPartialSnapshot:
    @pytest.mark.asyncio
    async def test_partial_updated_after_each_source_extract(self):
        from app.infrastructure.agents.research_prompt import (
            EvidenceItem as PromptEvidenceItem,
            ExtractedEvidence,
        )

        agent = ResearchAgent()
        input_data = ResearchInput(
            skip_evidence_evaluation=True,
            max_results_per_source=4,
            max_evidence_items=15,
        )
        results = [
            _raw_source(n=1, source_name="A"),
            _raw_source(n=1, source_name="B"),
        ]
        parsed = ExtractedEvidence(
            evidence_items=[
                PromptEvidenceItem(
                    title="t",
                    source="A",
                    url="https://example.com/A/0",
                    summary="s",
                    confidence="medium",
                    dimension="features",
                    date="",
                )
            ]
        )

        call_count = {"n": 0}

        async def slow_generate(**kwargs):
            call_count["n"] += 1
            await asyncio.sleep(0.01)
            if call_count["n"] == 1:
                return MagicMock(parsed=parsed, content="")
            return MagicMock(parsed=None, content="")

        with patch(
            "app.infrastructure.agents.research_agent.llm_client.generate",
            new=slow_generate,
        ):
            deduped, _ = await agent._extract_evidence_from_sources(
                "objective",
                results,
                input_data,
                4,
                lambda: 999.0,
                task_id="t1",
            )

        assert len(deduped) >= 1
        assert len(agent._partial_evidence_items) >= 1


class TestFastRegression:
    def test_fast_mode_config_unchanged(self):
        from app.infrastructure.workflow.analysis_mode import get_mode_config

        cfg = get_mode_config("fast")
        assert cfg.skip_compare is True
        assert cfg.skip_evidence_evaluation is True
        assert cfg.research_timeout_s == 120.0
        assert cfg.mode_total_budget_s == 360.0
