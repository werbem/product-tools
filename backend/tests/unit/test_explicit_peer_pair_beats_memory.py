"""Explicit A-vs-B in the current message must beat stale Project Memory peers."""

from __future__ import annotations

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.conversation_service import ConversationService
from app.application.services.intent_understanding_service import (
    _extract_peer_pair_from_text,
    _extract_subject_and_compare_peers,
    _resolve_peer_comparison,
)
from app.domain.entities.project_memory import ProjectMemory, ProjectMemoryEntities


def test_extract_didi_ruqi_peer_pair():
    text = "帮我完成滴滴出行和如祺出行的竞品分析报告，核心围绕着广东市场。"
    assert _extract_peer_pair_from_text(text) == ("滴滴出行", "如祺出行")


def test_feizhu_subject_then_compare_meituan_ctrip():
    """为什么飞猪…？请对比美团与携程 → company=飞猪, peers=美团/携程."""
    text = "为什么飞猪酒旅增长放缓？请对比美团与携程，并给出产品策略"
    assert _extract_subject_and_compare_peers(text) == ("飞猪", ["美团", "携程"])
    # Must NOT parse as A=对比美团 vs B=携程
    assert _extract_peer_pair_from_text(text) == (None, None)
    company, comps, product = _resolve_peer_comparison(
        "对比美团",
        ["携程"],
        "酒旅",
        text,
    )
    assert company == "飞猪"
    assert comps == ["美团", "携程"]
    assert product == "酒旅"


def test_resolve_peer_pair_overwrites_stale_memory_competitors():
    text = "帮我完成滴滴出行和如祺出行的竞品分析报告，核心围绕着广东市场。"
    company, comps, product = _resolve_peer_comparison(
        "滴滴打车",
        ["滴滴", "高德打车", "曹操出行"],
        "出行",
        text,
    )
    assert company == "滴滴出行"
    assert comps == ["如祺出行"]
    assert "高德打车" not in comps
    assert "曹操出行" not in comps
    assert product == "出行"


def test_merge_memory_partial_skips_stale_peers_on_explicit_pair():
    memory = ProjectMemory(
        project_id="p-ride",
        entities=ProjectMemoryEntities(
            our_company="滴滴打车",
            competitors=["滴滴", "高德打车", "曹操出行"],
            product="滴滴打车华南市场",
        ),
        last_objectives=["调研滴滴打车在华南市场发展趋势及其原因"],
    )
    text = "帮我完成滴滴出行和如祺出行的竞品分析报告，核心围绕着广东市场。"
    merged = ConversationService._merge_memory_partial(None, memory, raw_message=text)
    assert merged is not None
    assert merged.company in {"滴滴出行", "滴滴"}
    assert merged.competitors == ["如祺出行"]
    assert merged.objective is None


def test_fill_intent_from_memory_keeps_explicit_peers():
    memory = ProjectMemory(
        project_id="p-ride",
        entities=ProjectMemoryEntities(
            our_company="滴滴打车",
            competitors=["高德打车", "曹操出行"],
            product="出行",
        ),
    )
    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="滴滴出行",
        competitors=["如祺出行"],
        product="出行",
        confidence=0.85,
        needs_clarification=False,
        raw_message="帮我完成滴滴出行和如祺出行的竞品分析报告，核心围绕着广东市场。",
    )
    filled = ConversationService._fill_intent_from_memory(intent, memory)
    assert filled.competitors == ["如祺出行"]
    assert "高德打车" not in filled.competitors


def test_single_entity_still_can_use_memory_peers():
    """No A-vs-B in message → Memory peers remain available for suggest fill."""
    text = "继续分析滴滴打车的竞争优势，并给出产品策略建议"
    company, comps, product = _resolve_peer_comparison(
        "滴滴打车",
        ["高德打车", "曹操出行"],
        "出行",
        text,
    )
    assert company == "滴滴打车"
    assert comps == ["高德打车", "曹操出行"]
