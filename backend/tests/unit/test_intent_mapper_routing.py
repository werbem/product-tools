"""Workflow routing: analysis report wins over collection false positives."""

from __future__ import annotations

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.intent_mapper import (
    detect_analysis_intent,
    detect_collection_intent,
    is_intelligence_collection,
    resolve_workflow_kind,
    to_report_create_request,
)


def _intent(
    raw: str,
    *,
    company: str | None = "龙腾出行",
    competitors: list[str] | None = None,
    product: str | None = "机场场景",
    objective: str | None = "product_improvement",
) -> IntentUnderstandingResult:
    return IntentUnderstandingResult(
        type="competitive_analysis",
        company=company,
        competitors=competitors if competitors is not None else ["悦途"],
        product=product,
        objective=objective,
        confidence=0.9,
        raw_message=raw,
    )


class TestDetectSignals:
    def test_analysis_signals(self):
        assert detect_analysis_intent("竞品分析报告")
        assert detect_analysis_intent("竞品差异")
        assert detect_analysis_intent("Write a competitive analysis report")
        assert not detect_analysis_intent("帮我收集抖音近期信息")

    def test_collection_signals(self):
        assert detect_collection_intent("帮我收集字节跳动抖音近期商业发展信息")
        assert detect_collection_intent("收集携程会员体系资料")
        assert detect_collection_intent("调研一下美团酒店近期动态")
        assert not detect_collection_intent("商业行为有哪些类型？")
        assert not detect_collection_intent("市场信息很重要")


class TestResolveWorkflowKind:
    @pytest.mark.parametrize(
        "raw,competitors,expected",
        [
            (
                "帮我完成龙腾出行和悦途的机场场景的竞品分析报告，重点是商业行为、海外战略方向的竞品差异",
                ["悦途"],
                "deep_analysis",
            ),
            (
                "帮我收集字节跳动抖音近期商业发展信息",
                [],
                "intelligence_collection",
            ),
            (
                "收集携程会员体系资料",
                [],
                "intelligence_collection",
            ),
            (
                "对比飞猪和美团酒店，给出产品策略建议",
                ["美团"],
                "deep_analysis",
            ),
            (
                "调研一下美团酒店近期动态",
                [],
                "intelligence_collection",
            ),
            (
                "分析飞猪 vs 美团，并收集相关公开资料做支撑",
                ["美团"],
                "deep_analysis",
            ),
            (
                "Write a competitive analysis report on A vs B focusing on commercial behavior",
                ["B"],
                "deep_analysis",
            ),
        ],
    )
    def test_cases(self, raw, competitors, expected):
        company = "飞猪" if "飞猪" in raw or "A vs" in raw else "龙腾出行"
        if "字节" in raw:
            company, product = "字节跳动", "抖音"
        elif "携程" in raw and "收集" in raw:
            company, product = "携程", "会员体系"
        elif "美团酒店" in raw and "调研" in raw:
            company, product = "美团", "酒店"
        elif "competitive analysis" in raw.lower():
            company, product = "A", "product"
        else:
            product = "机场场景" if "机场" in raw else "酒店"
        intent = _intent(
            raw,
            company=company,
            competitors=competitors,
            product=product,
        )
        assert resolve_workflow_kind(intent) == expected
        assert is_intelligence_collection(intent) == (expected == "intelligence_collection")

    def test_commercial_behavior_alone_not_collection(self):
        raw = "商业行为有哪些类型？"
        assert not detect_collection_intent(raw)
        assert not detect_analysis_intent(raw)
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company=None,
            competitors=[],
            product=None,
            objective=None,
            confidence=0.4,
            raw_message=raw,
            needs_clarification=True,
            missing_fields=["company", "competitors", "product"],
        )
        # Must not classify as intelligence_collection solely due to 商业行为
        assert resolve_workflow_kind(intent) == "deep_analysis"
        assert not is_intelligence_collection(intent)


class TestToReportCreateRequestRouting:
    def test_original_bug_sentence_deep_analysis_with_focus_scene(self):
        raw = (
            "帮我完成龙腾出行和悦途的机场场景的竞品分析报告，"
            "重点是商业行为、海外战略方向的竞品差异"
        )
        intent = _intent(
            raw,
            company="龙腾出行",
            competitors=["悦途"],
            product="机场场景",
            objective="重点分析商业行为、海外战略方向的竞品差异",
        )
        req = to_report_create_request(intent, analysis_mode="full")
        assert req.optional["workflow_kind"] == "deep_analysis"
        assert "skip_evidence_evaluation" not in req.optional
        assert req.optional["analysis_mode"] == "full"
        assert req.competitor_company == "悦途"
        assert req.scene
        assert "商业行为" in req.scene or "海外战略" in req.scene
        assert "product_improvement" not in (req.scene or "")
        debug = req.optional["routing_debug"]
        assert debug["workflow_kind"] == "deep_analysis"
        assert debug["matched_analysis"]
        assert "商业行为" not in "".join(debug.get("matched_collection") or [])

    def test_collect_sentence_still_collection(self):
        raw = "帮我收集字节跳动抖音近期商业发展信息"
        intent = _intent(
            raw,
            company="字节跳动",
            competitors=[],
            product="抖音",
            objective="intelligence_collection",
        )
        req = to_report_create_request(intent, analysis_mode="fast")
        assert req.optional["workflow_kind"] == "intelligence_collection"
        assert req.optional.get("skip_evidence_evaluation") is True
        assert req.competitor_company == "公开市场与主要竞品"

    def test_analysis_plus_collect_prefers_deep(self):
        raw = "分析飞猪 vs 美团，并收集相关公开资料做支撑"
        intent = _intent(
            raw,
            company="飞猪",
            competitors=["美团"],
            product="酒店",
            objective="intelligence_collection",  # noisy LLM label
        )
        req = to_report_create_request(intent, analysis_mode="full")
        assert req.optional["workflow_kind"] == "deep_analysis"
        assert req.optional["routing_debug"]["routing_reason"] == (
            "analysis_signal_overrides_collection_keyword"
        )
