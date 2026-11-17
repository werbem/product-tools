"""Regression: extract_findings_from_report must not emit title：title duplicates."""

from __future__ import annotations

from app.application.services.memory_writer import (
    _is_title_variant,
    extract_findings_from_report,
)


class TestExtractFindingsFromReportTitleDedup:
    def test_sections_skip_title_echo_and_use_next_line(self) -> None:
        findings = extract_findings_from_report(
            markdown=None,
            sections=[
                {
                    "title": "一、Executive Summary",
                    "content": "一、Executive Summary\n滴滴在华南市场的份额仍领先高德与曹操出行。\n后续需关注运力补贴节奏。",
                },
            ],
            task_id="task-1",
        )
        assert len(findings) == 1
        assert findings[0].text.startswith("一、Executive Summary：")
        assert "滴滴在华南市场" in findings[0].text
        assert findings[0].text.count("一、Executive Summary") == 1

    def test_sections_skip_when_only_title_echo(self) -> None:
        findings = extract_findings_from_report(
            markdown=None,
            sections=[
                {
                    "title": "二、产品概览与定位",
                    "content": "二、产品概览与定位\n## 二、产品概览与定位",
                },
            ],
            task_id="task-2",
        )
        assert findings == []

    def test_sections_normal_body_unchanged(self) -> None:
        findings = extract_findings_from_report(
            markdown=None,
            sections=[
                {
                    "title": "三、目标用户与画像",
                    "content": "- 核心用户为一线城市高频出行人群，周末短途需求占比上升。",
                },
            ],
            task_id="task-3",
        )
        assert len(findings) == 1
        assert findings[0].text == (
            "三、目标用户与画像：核心用户为一线城市高频出行人群，周末短途需求占比上升。"
        )

    def test_markdown_skip_heading_echo(self) -> None:
        md = """# 互联网产品竞品分析报告

## 一、Executive Summary
一、Executive Summary
美团依托到店场景，在酒旅业务上具备明显的流量与用户触达优势。

## 二、产品概览与定位
二、产品概览与定位
"""
        findings = extract_findings_from_report(
            markdown=md,
            sections=None,
            task_id="task-md",
            limit=5,
        )
        texts = [f.text for f in findings]
        assert any("美团依托到店场景" in t for t in texts)
        assert all(t.count("一、Executive Summary") <= 1 for t in texts)
        # Second section has only title echo → no finding
        assert not any(t.startswith("二、产品概览与定位") for t in texts)

    def test_markdown_normal_heading_body_unchanged(self) -> None:
        md = """## 四、核心功能对比

双方在派单效率与司机供给上差异明显，滴滴在高峰期完单率更高。
"""
        findings = extract_findings_from_report(
            markdown=md,
            sections=None,
            task_id="task-md-2",
        )
        assert len(findings) == 1
        assert findings[0].text.startswith("四、核心功能对比：")
        assert "派单效率" in findings[0].text

    def test_is_title_variant_handles_numbering_and_emphasis(self) -> None:
        assert _is_title_variant("一、Executive Summary", "一、Executive Summary")
        assert _is_title_variant("**一、Executive Summary**", "一、Executive Summary")
        assert _is_title_variant("Executive Summary", "一、Executive Summary")
        assert not _is_title_variant(
            "滴滴在华南市场的份额仍领先",
            "一、Executive Summary",
        )
