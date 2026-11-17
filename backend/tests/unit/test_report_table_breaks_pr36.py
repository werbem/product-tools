"""Step 36: normalize HTML <br> in report markdown tables."""

from __future__ import annotations

from app.infrastructure.agents.report_agent import ReportAgent
from app.infrastructure.agents.report_prompt import SYSTEM_PROMPT, build_report_prompt


SWOT_WITH_BR = """## 十、SWOT 分析

|  | 优势 (S) | 劣势 (W) |
|------|------|------|
| **内部** | 阿里生态 [E004]<br>一站式产品 [E004] | 供应链不足 [E009]<br>心智模糊 [E013] |
| **外部** | 行业复苏 [E008]<br />出海潜力 [E003] | 美团渗透 [E001]<br/>监管不确定性 [E015] |
"""


class TestNormalizeTableBreaks:
    def test_replaces_br_variants_with_semicolon(self):
        out = ReportAgent.normalize_table_breaks(SWOT_WITH_BR)
        assert "<br" not in out.lower()
        assert "阿里生态 [E004]；一站式产品 [E004]" in out
        assert "行业复苏 [E008]；出海潜力 [E003]" in out
        assert "美团渗透 [E001]；监管不确定性 [E015]" in out

    def test_preserves_table_pipe_structure(self):
        out = ReportAgent.normalize_table_breaks(SWOT_WITH_BR)
        rows = [ln for ln in out.splitlines() if ln.startswith("|")]
        assert len(rows) >= 3
        for row in rows:
            # header / separator / data rows keep column pipes
            assert row.count("|") >= 3

    def test_noop_when_no_br(self):
        clean = "| **内部** | A；B | C；D |"
        assert ReportAgent.normalize_table_breaks(clean) == clean

    def test_empty_safe(self):
        assert ReportAgent.normalize_table_breaks("") == ""
        assert ReportAgent.normalize_table_breaks(None) == ""  # type: ignore[arg-type]


class TestStripPartyRoleLabels:
    def test_strips_wofang_suffix_in_tables(self):
        md = "| 维度 | 抖音（我方） | 快手 |\n|------|------|------|\n"
        out = ReportAgent.strip_party_role_labels(md)
        assert "（我方）" not in out
        assert "| 抖音 |" in out or "抖音 |" in out

    def test_strips_fenxifang_and_ascii(self):
        md = "列：飞猪（分析方） vs 美团(竞品)"
        out = ReportAgent.strip_party_role_labels(md)
        assert "（分析方）" not in out
        assert "(竞品)" not in out
        assert "飞猪" in out and "美团" in out

    def test_prepare_markdown_chains_strip(self):
        md = "| 抖音（我方） | A<br>B |"
        out = ReportAgent._prepare_markdown(md)
        assert "（我方）" not in out
        assert "<br" not in out.lower()


class TestReportPromptNoBr:
    def test_system_prompt_forbids_br(self):
        assert "禁止输出 HTML" in SYSTEM_PROMPT
        assert "<br>" in SYSTEM_PROMPT  # mentioned as forbidden example

    def test_template_swot_uses_semicolon_not_br(self):
        from app.infrastructure.agents import report_prompt as rp

        src = open(rp.__file__, encoding="utf-8").read()
        assert "[Strength 1] [E001]；[Strength 2] [E002]" in src
        # Template cells must not instruct LLM to emit HTML breaks
        assert "| [Strength 1] [E001]<br>" not in src
        assert build_report_prompt  # import used / keep lint quiet
        _ = build_report_prompt(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
        )
