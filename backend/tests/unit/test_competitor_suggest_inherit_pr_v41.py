"""Placeholder competitors + suggested peers inheritance."""

from __future__ import annotations

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.intent_entities import (
    is_placeholder_entity,
    looks_like_competitor_listing_query,
    sanitize_competitors,
    suggest_default_competitors,
)
from app.application.services.intent_mapper import to_report_create_request
from app.application.services.intent_understanding_service import (
    _extract_peer_pair_from_text,
)
from app.application.services.conversation_service import ConversationService
from app.domain.entities.message import Message


def test_placeholder_and_peer_skip():
    assert is_placeholder_entity("竞品公司")
    assert is_placeholder_entity("竞品公司的竞品分析报告")
    assert is_placeholder_entity("竞品公司的")
    assert _extract_peer_pair_from_text("帮我完成携程和竞品公司的竞品分析报告") == (
        None,
        None,
    )
    assert _extract_peer_pair_from_text("携程对比美团") == ("携程", "美团")


def test_mapper_rejects_placeholder_competitors():
    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="携程",
        competitors=["竞品公司的竞品分析报告"],
        product="在线旅游",
        confidence=0.8,
        needs_clarification=False,
        raw_message="帮我完成携程和竞品公司的竞品分析报告",
    )
    try:
        to_report_create_request(intent, analysis_mode="fast")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "competitors" in str(exc)


def test_suggest_defaults_xiecheng():
    peers = suggest_default_competitors("携程", "OTA")
    assert "美团" in peers
    assert "飞猪" in peers
    assert sanitize_competitors(peers + ["竞品公司"], "携程") == peers


def test_you_shenme_jingpin_listing_and_subject():
    from app.application.services.intent_entities import (
        extract_listing_subject_company,
        looks_like_competitor_listing_query,
        resolve_competitor_suggestions,
    )
    from app.application.services.router_service import RouterService
    from app.application.dto.intent_dto import IntentUnderstandingResult
    from app.application.services.conversation_service import ConversationService

    for text, company in (
        ("京东外卖有什么竞品？", "京东外卖"),
        ("美团外卖有什么竞品？", "美团外卖"),
        ("拼多多的竞品有哪些？", "拼多多"),
    ):
        assert looks_like_competitor_listing_query(text)
        assert extract_listing_subject_company(text) == company
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company="饿了么",  # stale partial
            competitors=[],
            product="外卖",
            confidence=0.9,
            needs_clarification=True,
            missing_fields=["competitors"],
            raw_message=text,
        )
        fixed = ConversationService._apply_listing_subject_to_intent(intent, text)
        assert fixed.company == company
        assert fixed.needs_clarification is False
        rd = RouterService().route(fixed, text)
        assert rd.workflow_type == "simple_question"
        peers = resolve_competitor_suggestions(fixed.company, fixed.product, None)["peers"]
        assert peers
        assert company not in peers or company == "美团外卖"  # self excluded for 京东
        if company == "京东外卖":
            assert "美团" in peers or "饿了么" in peers
        if company == "美团外卖":
            assert "饿了么" in peers
        if company == "拼多多":
            assert "淘宝" in peers or "京东" in peers


def test_suggest_defaults_pinduoduo_ecommerce():
    from app.application.services.intent_entities import infer_default_product

    peers = suggest_default_competitors("拼多多", None)
    assert "淘宝" in peers
    assert "京东" in peers
    assert "拼多多" not in peers
    assert infer_default_product("拼多多") == "电商"
    # Delivery must still win over ecommerce for 京东外卖
    delivery = suggest_default_competitors("京东外卖", "外卖")
    assert "饿了么" in delivery or "美团" in delivery


def test_apply_suggested_competitors_fills_product_for_pinduoduo():
    from app.application.dto.intent_dto import IntentUnderstandingResult

    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="拼多多",
        competitors=[],
        product=None,
        confidence=0.8,
        missing_fields=["product"],
        needs_clarification=True,
        raw_message="用这些竞品做分析",
    )
    messages = [
        Message(
            id="m1",
            conversation_id="conv-pdd",
            role="assistant",
            content="常见对比对象：淘宝、京东、抖音电商",
            metadata={
                "message_type": "question_answered",
                "intent": {
                    "type": "competitive_analysis",
                    "company": "拼多多",
                    "competitors": ["淘宝", "京东", "抖音电商"],
                    "product": None,
                },
                "suggested_competitors": ["淘宝", "京东", "抖音电商"],
            },
        ),
    ]

    class _Store:
        def list_messages_by_conversation(self, conversation_id: str):
            return messages

    svc = ConversationService.__new__(ConversationService)
    svc._message_store = _Store()
    fixed = svc._apply_suggested_competitors(intent, "conv-pdd", "用这些竞品做分析")
    assert fixed.needs_clarification is False
    assert fixed.product == "电商"
    assert fixed.competitors == ["淘宝", "京东", "抖音电商"]
    req = to_report_create_request(fixed, analysis_mode="fast")
    assert req.our_company == "拼多多"
    assert req.product == "电商"


def test_apply_suggested_when_competitors_already_present_still_fills_product():
    """Regression: early return on existing comps left product=None → forever clarify."""
    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="拼多多",
        competitors=["淘宝", "京东", "抖音电商"],
        product=None,
        confidence=0.8,
        missing_fields=["product"],
        needs_clarification=True,
        clarification_question="请补充缺失的信息以便开始分析。",
        raw_message="用这些竞品做分析",
    )
    svc = ConversationService.__new__(ConversationService)
    svc._message_store = type("S", (), {"list_messages_by_conversation": lambda *_: []})()
    fixed = svc._apply_suggested_competitors(intent, "conv-x", "用这些竞品做分析")
    assert fixed.needs_clarification is False
    assert fixed.product == "电商"
    assert fixed.competitors == ["淘宝", "京东", "抖音电商"]


def test_single_entity_analysis_autofills_curated_peers():
    """「分析携程酒店竞争优势」→ Memory/curated peers, no clarification."""
    from app.application.services.intent_mapper import detect_analysis_intent

    text = "分析携程酒店业务的竞争优势，并给出产品策略建议"
    assert detect_analysis_intent(text)
    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="携程",
        competitors=[],
        product="酒店业务",
        confidence=0.9,
        missing_fields=["competitors"],
        needs_clarification=True,
        clarification_question="请告诉我主要对比哪些竞品？",
        raw_message=text,
    )
    svc = ConversationService.__new__(ConversationService)
    svc._message_store = type("S", (), {"list_messages_by_conversation": lambda *_: []})()
    fixed = svc._apply_suggested_competitors(intent, "conv-xiecheng", text, memory=None)
    assert fixed.needs_clarification is False
    assert "competitors" not in (fixed.missing_fields or [])
    assert fixed.competitors
    assert "美团" in fixed.competitors or "飞猪" in fixed.competitors
    req = to_report_create_request(fixed, analysis_mode="fast")
    assert req.our_company == "携程"


def test_recover_partial_from_question_answered_suggestions():
    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="携程",
        competitors=["美团", "飞猪", "同程旅行"],
        product="在线旅游",
        confidence=0.7,
        needs_clarification=False,
        raw_message="携程的常见竞品公司有哪些？",
    )
    messages = [
        Message(
            id="m1",
            conversation_id="conv-suggest-1",
            role="assistant",
            content="参考常见竞品：美团、飞猪、同程旅行。",
            metadata={
                "message_type": "question_answered",
                "intent": intent.model_dump(),
                "suggested_competitors": ["美团", "飞猪", "同程旅行"],
            },
        )
    ]

    class _Store:
        def list_messages_by_conversation(self, conversation_id: str):
            return messages

    svc = ConversationService.__new__(ConversationService)
    svc._message_store = _Store()
    partial = ConversationService._recover_partial(svc, "conv-suggest-1")
    assert partial is not None
    assert partial.company == "携程"
    assert "美团" in (partial.competitors or [])

    suggested = ConversationService._recover_suggested_competitors(svc, "conv-suggest-1")
    assert suggested[:1] == ["美团"]
