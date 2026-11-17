"""Generic collection search query: 公司 + 产品 + 用户要求内容."""

from __future__ import annotations

from app.application.services.intent_entities import (
    compose_entity_user_search_query,
    extract_user_request_focus,
)
from app.infrastructure.agents.research_agent import ResearchAgent


def test_extract_focus_strips_collect_verbs_and_entities() -> None:
    focus = extract_user_request_focus(
        "帮我收集字节跳动抖音近期产品策略发展信息",
        company="字节跳动",
        product="抖音",
    )
    assert "产品策略" in focus
    assert "字节跳动" not in focus
    assert "抖音" not in focus
    assert "帮我收集" not in focus


def test_compose_uses_company_product_and_user_focus() -> None:
    q = compose_entity_user_search_query(
        company="字节跳动",
        product="抖音",
        user_query="帮我收集字节跳动抖音近期产品策略发展信息",
    )
    assert "字节跳动" in q
    assert "抖音" in q
    assert "产品策略" in q
    assert "商业发展" not in q  # must not hardcode prior one-off topic


def test_compose_falls_back_to_objective_when_no_user_query() -> None:
    q = compose_entity_user_search_query(
        company="美团",
        product="外卖",
        user_query="",
        objective="收集美团外卖近期增长策略",
    )
    assert "美团" in q
    assert "外卖" in q
    assert "增长" in q or "策略" in q


def test_compose_drops_placeholder_product() -> None:
    q = compose_entity_user_search_query(
        company="拼多多",
        product="公开市场与主要竞品",
        user_query="帮我收集拼多多近期商业发展信息",
    )
    assert "拼多多" in q
    assert "公开市场" not in q
    assert "商业发展" in q


def test_source_results_usable_requires_items() -> None:
    class _R:
        def __init__(self, status: str, items: list):
            self.status = status
            self.items = items

    assert ResearchAgent._source_results_usable([]) is False
    assert ResearchAgent._source_results_usable([_R("success", [])]) is False
    assert ResearchAgent._source_results_usable([_R("no_data", [])]) is False
    assert ResearchAgent._source_results_usable([_R("success", [{"x": 1}])]) is True
