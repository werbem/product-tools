"""PR3: Fast mode report — 13 chapters in 3 sequential segments."""

from __future__ import annotations

import asyncio
import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.application.dto.agent_dto import ReportInput
from app.config.constants import Phase
from app.infrastructure.agents.base import AgentContext
from app.infrastructure.agents.report_agent import (
    FAST_REPORT_SEGMENTS,
    ReportAgent,
    SECTION_DEFS,
)
from app.infrastructure.agents.report_prompt import (
    SEGMENT_SECTION_TITLES,
    build_report_prompt_segment,
)


def _segment_markdown(segment: int) -> str:
    titles = SEGMENT_SECTION_TITLES[segment]  # type: ignore[index]
    return "\n\n".join(f"## {title}\n\nSegment {segment} body." for title in titles)


def _report_input(*, fast: bool = True) -> ReportInput:
    return ReportInput(
        evidence_bundle={"evidence_items": [], "sources_used": []},
        gap_analysis={},
        strategic_insights={},
        our_company="Acme",
        competitor_company="Beta",
        product="Widget",
        objective="product_improvement",
        fast_mode=fast,
        llm_timeout_seconds=180.0,
        segment_timeout_seconds=55.0,
        output_formats=["markdown"],
    )


@pytest.fixture
def ctx() -> AgentContext:
    return AgentContext(task_id="pr3-task", current_phase=Phase.REPORTING)


class TestSegmentPrompts:
    def test_segment1_prompt_includes_compare_chapter_and_fast_note(self):
        prompt = build_report_prompt_segment(
            segment=1,
            our_company="A",
            competitor_company="B",
            product="P",
            objective="product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
            fast_mode=True,
        )
        assert "分段 1/3" in prompt
        assert "四、核心功能对比" in prompt
        assert "基于证据整理" in prompt
        assert "只输出下列章节" in prompt

    def test_segment2_prompt_covers_chapters_5_to_9(self):
        prompt = build_report_prompt_segment(
            segment=2,
            our_company="A",
            competitor_company="B",
            product="P",
            objective="product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
        )
        for title in SEGMENT_SECTION_TITLES[2]:
            assert title in prompt
        assert "分段 2/3" in prompt

    def test_segment3_prompt_covers_chapters_10_to_13(self):
        prompt = build_report_prompt_segment(
            segment=3,
            our_company="A",
            competitor_company="B",
            product="P",
            objective="product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
        )
        for title in SEGMENT_SECTION_TITLES[3]:
            assert title in prompt


class TestSegmentedGeneration:
    @pytest.mark.asyncio
    async def test_fast_mode_calls_llm_three_times_sequentially(self, ctx: AgentContext):
        agent = ReportAgent()
        call_order: list[int] = []

        async def fake_generate(**kwargs):
            user_prompt = kwargs.get("user_prompt", "")
            if "分段 1/3" in user_prompt:
                seg = 1
            elif "分段 2/3" in user_prompt:
                seg = 2
            else:
                seg = 3
            call_order.append(seg)
            return MagicMock(
                content=_segment_markdown(seg),
                prompt_tokens=10,
                completion_tokens=20,
            )

        with patch(
            "app.infrastructure.agents.report_agent.llm_client.generate",
            new=AsyncMock(side_effect=fake_generate),
        ):
            with patch.object(ReportAgent, "_touch_segment_progress"):
                result = await agent.arun(ctx, _report_input(fast=True))

        assert call_order == [1, 2, 3]
        assert result.success is True
        md = result.output.report_document.formats.markdown
        for title, _ in SECTION_DEFS:
            assert f"## {title}" in md
        meta = result.output.report_document.metadata
        assert meta["generation_mode"] == "fast_segmented"
        assert meta["segment_timeouts"] == []
        assert meta["fast_mode"] is True

    @pytest.mark.asyncio
    async def test_full_mode_single_llm_call(self, ctx: AgentContext):
        agent = ReportAgent()
        calls = 0

        async def fake_generate(**kwargs):
            nonlocal calls
            calls += 1
            body = "\n\n".join(f"## {title}\n\nFull content." for title, _ in SECTION_DEFS)
            return MagicMock(content=body, prompt_tokens=5, completion_tokens=5)

        with patch(
            "app.infrastructure.agents.report_agent.llm_client.generate",
            new=AsyncMock(side_effect=fake_generate),
        ):
            result = await agent.arun(ctx, _report_input(fast=False))

        assert calls == 1
        assert result.success is True
        assert result.output.report_document.metadata.get("generation_mode") == "full_single"

    @pytest.mark.asyncio
    async def test_segment2_timeout_uses_fallback_other_segments_kept(self, ctx: AgentContext):
        agent = ReportAgent()

        async def fake_seg(agent, input_data, segment, *args, **kwargs):
            if segment == 2:
                raise asyncio.TimeoutError()
            return _segment_markdown(segment), 8, 8

        with patch.object(ReportAgent, "_generate_segment", new=fake_seg):
            with patch.object(ReportAgent, "_touch_segment_progress"):
                result = await agent.arun(ctx, _report_input(fast=True))

        md = result.output.report_document.formats.markdown
        assert "Segment 1 body." in md
        assert "降级为证据要点拼装" in md
        assert "Segment 3 body." in md
        meta = result.output.report_document.metadata
        assert meta["segment_timeouts"] == [2]
        assert meta["segment_retries"] == [2]
        assert meta["segment_evidence_fallback"] == [2]
        for title, _ in SECTION_DEFS:
            assert f"## {title}" in md

    @pytest.mark.asyncio
    async def test_segment_retry_recovers_without_fallback(self, ctx: AgentContext):
        agent = ReportAgent()
        attempts: dict[int, int] = {}

        async def fake_seg(agent, input_data, segment, *args, **kwargs):
            attempts[segment] = attempts.get(segment, 0) + 1
            if segment == 1 and attempts[segment] == 1:
                raise asyncio.TimeoutError()
            return _segment_markdown(segment), 2, 2

        with patch.object(ReportAgent, "_generate_segment", new=fake_seg):
            with patch.object(ReportAgent, "_touch_segment_progress"):
                result = await agent.arun(ctx, _report_input(fast=True))

        meta = result.output.report_document.metadata
        assert meta["segment_timeouts"] == []
        assert meta["segment_retries"] == [1]
        assert meta["segment_evidence_fallback"] == []
        assert "Segment 1 body." in result.output.report_document.formats.markdown
        assert attempts[1] == 2

    @pytest.mark.asyncio
    async def test_low_remaining_budget_skips_late_segments_with_fallback(self, ctx: AgentContext):
        agent = ReportAgent()
        llm_calls = 0
        mono_seq = [0.0, 0.0, 172.0, 173.0]
        mono_idx = 0

        def fake_monotonic() -> float:
            nonlocal mono_idx
            if mono_idx < len(mono_seq):
                value = mono_seq[mono_idx]
                mono_idx += 1
                return value
            return 174.0

        async def fake_generate(**kwargs):
            nonlocal llm_calls
            llm_calls += 1
            return MagicMock(content=_segment_markdown(1), prompt_tokens=1, completion_tokens=1)

        with patch(
            "app.infrastructure.agents.report_agent.llm_client.generate",
            new=AsyncMock(side_effect=fake_generate),
        ):
            with patch(
                "app.infrastructure.agents.report_agent.time.monotonic",
                side_effect=fake_monotonic,
            ):
                with patch.object(ReportAgent, "_touch_segment_progress"):
                    result = await agent.arun(ctx, _report_input(fast=True))

        assert llm_calls == 1
        meta = result.output.report_document.metadata
        assert meta["segment_timeouts"] == [2, 3]
        assert meta["segment_evidence_fallback"] == [2, 3]
        assert "降级为证据要点拼装" in result.output.report_document.formats.markdown
        for title, _ in SECTION_DEFS:
            assert f"## {title}" in result.output.report_document.formats.markdown

    @pytest.mark.asyncio
    async def test_segment_wait_for_budget_capped_at_55(self, ctx: AgentContext):
        agent = ReportAgent()
        budgets: list[float] = []

        async def capture_budget(agent, input_data, segment, *args, **kwargs):
            budgets.append(args[-1])
            return _segment_markdown(segment), 1, 1

        with patch.object(ReportAgent, "_generate_segment", new=capture_budget):
            with patch.object(ReportAgent, "_touch_segment_progress"):
                await agent.arun(ctx, _report_input(fast=True))

        assert len(budgets) == 3
        assert all(b <= 55.0 for b in budgets)

    def test_fast_timeout_fallback_has_thirteen_chapters_and_metadata(self):
        agent = ReportAgent()
        result = agent.build_timeout_fallback(_report_input(fast=True))
        md = result.output.report_document.formats.markdown
        section_headers = re.findall(r"^## .+", md, flags=re.MULTILINE)
        assert len([h for h in section_headers if any(h == f"## {t}" for t, _ in SECTION_DEFS)]) == 13
        meta = result.output.report_document.metadata
        assert meta["generation_mode"] == "fast_segmented"
        assert meta["segment_timeouts"] == [1, 2, 3]
        assert meta["report_timeout_fallback"] is True


class TestMergeAndSections:
    def test_merge_segments_preserves_chapter_order(self):
        input_data = _report_input()
        segments = [_segment_markdown(n) for n in (1, 2, 3)]
        merged = ReportAgent._merge_segments(input_data, segments)
        positions = [merged.index(f"## {title}") for title, _ in SECTION_DEFS]
        assert positions == sorted(positions)

    def test_extract_sections_finds_all_thirteen(self):
        input_data = _report_input()
        segments = [_segment_markdown(n) for n in (1, 2, 3)]
        merged = ReportAgent._merge_segments(input_data, segments)
        sections = ReportAgent._extract_sections(merged)
        assert len(sections) == 13
        assert all(s.word_count > 0 for s in sections)

    def test_segment_timeout_fallback_per_chapter(self):
        fb = ReportAgent._build_segment_timeout_fallback(2, FAST_REPORT_SEGMENTS[2])
        assert fb.count("降级为证据要点拼装") == len(FAST_REPORT_SEGMENTS[2])
        for title, _ in FAST_REPORT_SEGMENTS[2]:
            assert f"## {title}" in fb

    def test_segment_evidence_fallback_uses_evidence_bullets(self):
        evidence = json.dumps(
            [
                {"title": "拼多多活跃用户", "content": "月活增长", "source": "公开报道"},
                {"title": "淘宝生态", "content": "商家规模领先", "source": "研报"},
            ],
            ensure_ascii=False,
        )
        fb = ReportAgent._build_segment_evidence_fallback(
            1,
            FAST_REPORT_SEGMENTS[1],
            _report_input(fast=True),
            evidence,
        )
        assert "降级为证据要点拼装" in fb
        assert "拼多多活跃用户" in fb or "淘宝生态" in fb
        assert "本章生成超时，请稍后重试" not in fb
        for title, _ in FAST_REPORT_SEGMENTS[1]:
            assert f"## {title}" in fb
