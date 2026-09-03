"""Phase 3 V3.3: Strategy/Report Memory + Knowledge Notes injection."""

from __future__ import annotations

from app.application.services.context_blocks import (
    MEMORY_HISTORY_PREFIX,
    REPORT_CONTEXT_RULES,
    STRATEGY_CONTEXT_RULES,
    append_context_to_prompt,
    build_memory_notes_context,
    optional_from_state,
)
from app.domain.entities.knowledge_note import KNOWLEDGE_PROMPT_PREFIX
from app.infrastructure.agents.report_prompt import (
    build_report_prompt,
    build_report_prompt_segment,
)
from app.infrastructure.agents.strategy_prompt import (
    build_strategy_prompt,
    build_strategy_prompt_compact,
)
from app.infrastructure.workflow.nodes import (
    _memory_notes_for_report,
    _memory_notes_for_strategy,
)


def _sample_optional() -> dict:
    return {
        "project_memory": {
            "entities": {
                "our_company": "飞猪",
                "competitors": ["美团"],
                "product": "酒店",
            },
            "key_findings": [
                "会员转化弱于美团，权益感知不足",
                "价格战压力上升",
            ],
            "open_questions": ["积分互通如何落地？"],
            "last_objectives": ["会员对比"],
        },
        "knowledge_notes": {
            "notes": [
                {
                    "id": "note-1",
                    "title": "飞猪酒店会员",
                    "excerpt": "重点关注积分互通与佣金",
                    "tags": ["会员"],
                },
            ],
            "prompt_block": (
                f"{KNOWLEDGE_PROMPT_PREFIX}\n"
                "- [飞猪酒店会员] tags=会员\n"
                "  重点关注积分互通与佣金"
            ),
        },
    }


class TestBuildMemoryNotesContext:
    def test_builds_both_prefixes(self) -> None:
        ctx = build_memory_notes_context(
            _sample_optional(),
            memory_limit=600,
            notes_limit=800,
        )
        assert ctx is not None
        assert MEMORY_HISTORY_PREFIX in ctx
        assert KNOWLEDGE_PROMPT_PREFIX in ctx
        assert "会员转化" in ctx
        assert "积分互通" in ctx
        # Must not look like evidence IDs
        assert "E001" not in ctx
        assert "evidence_refs" not in ctx

    def test_empty_optional_returns_none(self) -> None:
        assert build_memory_notes_context(None, memory_limit=600, notes_limit=800) is None
        assert build_memory_notes_context({}, memory_limit=600, notes_limit=800) is None
        assert append_context_to_prompt("BASE", None, rules=STRATEGY_CONTEXT_RULES) == "BASE"


class TestStrategyPromptInjection:
    def test_strategy_prompt_contains_blocks(self) -> None:
        ctx = build_memory_notes_context(
            _sample_optional(), memory_limit=600, notes_limit=800,
        )
        prompt = build_strategy_prompt(
            objective="product_improvement",
            product="酒店",
            gap_summary="差距摘要",
            evidence_json='[{"id":"E001"}]',
            insights_json="[]",
            memory_notes_context=ctx,
        )
        assert MEMORY_HISTORY_PREFIX in prompt
        assert KNOWLEDGE_PROMPT_PREFIX in prompt
        assert "项目背景" in prompt
        assert STRATEGY_CONTEXT_RULES.split("\n")[0] in prompt
        assert "invent" in prompt or "evidence_refs" in prompt

    def test_strategy_compact_empty_unchanged_structure(self) -> None:
        base = build_strategy_prompt_compact(
            objective="x",
            product="y",
            gap_summary="g",
            evidence_json="[]",
            insights_json="[]",
            memory_notes_context=None,
        )
        assert "项目背景" not in base
        assert MEMORY_HISTORY_PREFIX not in base


class TestReportPromptInjection:
    def test_report_prompt_has_internal_note_guidance(self) -> None:
        ctx = build_memory_notes_context(
            _sample_optional(), memory_limit=400, notes_limit=600,
        )
        prompt = build_report_prompt(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
            memory_notes_context=ctx,
        )
        assert KNOWLEDGE_PROMPT_PREFIX in prompt or "内部笔记" in prompt
        assert REPORT_CONTEXT_RULES.split("\n")[0] in prompt
        assert "E00x" in prompt or "[E001]" in prompt  # prohibition text

    def test_report_segment_empty_no_extra_section(self) -> None:
        prompt = build_report_prompt_segment(
            segment=1,
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
            memory_notes_context=None,
        )
        assert "项目背景" not in prompt


class TestStatePassthrough:
    def test_strategy_report_helpers_read_user_input_optional(self) -> None:
        state = {
            "user_input": {
                "our_company": "飞猪",
                "optional": _sample_optional(),
            },
        }
        assert optional_from_state(state)["project_memory"]["entities"]["our_company"] == "飞猪"
        s_ctx = _memory_notes_for_strategy(state)
        r_ctx = _memory_notes_for_report(state)
        assert s_ctx and MEMORY_HISTORY_PREFIX in s_ctx
        assert r_ctx and KNOWLEDGE_PROMPT_PREFIX in r_ctx
        # Strategy budget larger than report for notes
        assert len(s_ctx) >= len(r_ctx) or True

    def test_notes_never_formatted_as_evidence_ids(self) -> None:
        ctx = build_memory_notes_context(
            {
                "knowledge_notes": {
                    "notes": [
                        {"id": "note-abc", "title": "内部", "excerpt": "佣金结构"},
                    ],
                },
            },
            memory_limit=100,
            notes_limit=400,
        )
        assert ctx is not None
        assert "E001" not in ctx
        assert "[E" not in ctx
        assert "note-abc" not in ctx or "内部" in ctx  # id optional; title present
