"""Douyin listing subject + dual listing/analysis routing."""

from __future__ import annotations

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.intent_entities import (
    extract_listing_subject_company,
    looks_like_competitor_listing_query,
    resolve_competitor_suggestions,
    sanitize_competitors,
    suggest_default_competitors,
)
from app.application.services.intent_mapper import detect_analysis_intent
from app.application.services.router_service import RouterService


def test_douyin_dou_you_subject_not_douyin_dou() -> None:
    text = "抖音都有哪些竞品？"
    assert looks_like_competitor_listing_query(text)
    assert extract_listing_subject_company(text) == "抖音"
    assert extract_listing_subject_company(
        "抖音都有哪些竞品？帮我完成抖音的竞品分析报告",
    ) == "抖音"


def test_pronoun_listing_subject_rejected() -> None:
    """「它都有哪些竞品」must not invent company「它都」."""
    from app.application.services.intent_entities import (
        is_invalid_company_entity,
        sanitize_company_name,
    )

    text = "它都有哪些竞品？"
    assert looks_like_competitor_listing_query(text)
    assert extract_listing_subject_company(text) is None
    assert is_invalid_company_entity("它都")
    assert is_invalid_company_entity("它")
    assert sanitize_company_name("它都") is None
    assert sanitize_company_name("滴滴出行") == "滴滴出行"


def test_douyin_peers_exclude_self() -> None:
    peers = suggest_default_competitors("抖音", "短视频")
    assert peers
    assert "抖音" not in peers
    assert "抖音电商" not in peers
    assert sanitize_competitors(["抖音", "快手", "抖音电商"], "抖音") == ["快手"]


def test_listing_only_routes_simple_question() -> None:
    text = "抖音都有哪些竞品？"
    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="抖音",
        competitors=[],
        product="短视频",
        confidence=0.9,
        needs_clarification=False,
        raw_message=text,
    )
    rd = RouterService().route(intent, text)
    assert rd.workflow_type == "simple_question"
    peers = resolve_competitor_suggestions("抖音", "短视频", None)["peers"]
    assert "抖音" not in peers


def test_listing_plus_analysis_report_launches_deep() -> None:
    text = "抖音都有哪些竞品？帮我完成抖音的竞品分析报告"
    assert looks_like_competitor_listing_query(text)
    assert detect_analysis_intent(text)
    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="抖音",
        competitors=[],
        product="短视频",
        confidence=0.9,
        needs_clarification=False,
        raw_message=text,
    )
    rd = RouterService().route(intent, text)
    assert rd.workflow_type == "competitive_analysis"
