"""Step 38: Collection topic follows user language (zh/en)."""

from __future__ import annotations

from app.application.services.collection_formatter import build_collection_markdown
from app.application.services.collection_topic import (
    resolve_collection_topic,
    resolve_collection_topic_from_state,
)


class TestResolveCollectionTopic:
    def test_chinese_scene_preferred_over_enum(self):
        result = resolve_collection_topic(
            scene="收集字节跳动抖音近期商业发展信息",
            raw_message="帮我收集字节跳动抖音近期商业发展信息",
            objective="product_improvement",
            objective_code="product_improvement",
        )
        assert result["topic"] == "收集字节跳动抖音近期商业发展信息"
        assert result["topic_source"] == "scene"
        assert result["objective_code"] == "product_improvement"
        assert "product_improvement" not in result["topic"]

    def test_english_raw_message_when_no_scene(self):
        result = resolve_collection_topic(
            scene="",
            raw_message="Collect recent ByteDance Douyin business developments",
            objective="product_improvement",
            objective_code="product_improvement",
        )
        assert result["topic"] == "Collect recent ByteDance Douyin business developments"
        assert result["topic_source"] == "raw_message"

    def test_enum_only_maps_zh_with_cjk_hint(self):
        result = resolve_collection_topic(
            scene="",
            raw_message="",
            objective="product_improvement",
            language_hints=("字节跳动", "抖音"),
        )
        assert result["topic"] == "产品改进分析"
        assert result["topic_source"] == "objective_label"
        assert result["objective_code"] == "product_improvement"

    def test_enum_only_maps_en_without_cjk(self):
        result = resolve_collection_topic(
            scene="",
            raw_message="",
            objective="product_improvement",
            language_hints=("ByteDance", "Douyin"),
        )
        assert result["topic"] == "Product improvement"
        assert result["topic_source"] == "objective_label"

    def test_never_expose_snake_case_enum(self):
        for code in (
            "product_improvement",
            "go_to_market",
            "feature_benchmark",
            "competitive_defense",
        ):
            result = resolve_collection_topic(objective=code, language_hints=("公司",))
            assert "_" not in result["topic"]
            assert result["topic"] != code


class TestFormatterAndState:
    def test_markdown_uses_chinese_scene_not_enum(self):
        state = {
            "user_input": {
                "our_company": "字节跳动",
                "competitor_company": "公开市场与主要竞品",
                "product": "抖音",
                "objective": "product_improvement",
                "scene": "收集字节跳动抖音近期商业发展信息",
                "optional": {
                    "raw_message": "帮我收集字节跳动抖音近期商业发展信息",
                },
            },
            "validated_input": {
                "our_company": "字节跳动",
                "product": "抖音",
                "objective": "product_improvement",
                "scene": "",
            },
            "evidence_bundle": {"evidence_items": []},
            "collection_meta": {"sources_attempted": 1, "sources_succeeded": 1},
        }
        md = build_collection_markdown(state)
        assert "收集主题**：收集字节跳动抖音近期商业发展信息" in md
        assert "product_improvement" not in md

    def test_old_document_without_topic_fields_resolves_from_scene(self):
        state = {
            "user_input": {
                "our_company": "字节跳动",
                "product": "抖音",
                "objective": "product_improvement",
                "scene": "收集字节跳动抖音近期商业发展信息",
                "optional": {"raw_message": "帮我收集…"},
            },
            "validated_input": {"objective": "product_improvement"},
            "collection_document": {
                "markdown": "> **收集主题**：product_improvement\n",
                # no topic / topic_source keys (legacy)
            },
        }
        info = resolve_collection_topic_from_state(state)
        assert info["topic"] == "收集字节跳动抖音近期商业发展信息"
        assert info["topic_source"] == "scene"

    def test_persisted_topic_fields_preferred(self):
        state = {
            "user_input": {"objective": "product_improvement", "scene": "ignored"},
            "collection_document": {
                "topic": "Persisted English topic",
                "topic_source": "scene",
                "objective_code": "product_improvement",
            },
        }
        info = resolve_collection_topic_from_state(state)
        assert info["topic"] == "Persisted English topic"
        assert info["topic_source"] == "scene"

    def test_apply_topic_rewrites_legacy_markdown_line(self):
        from app.application.services.collection_topic import apply_topic_to_markdown

        md = "> **收集主题**：product_improvement\n> **生成时间**：x\n"
        out = apply_topic_to_markdown(md, "收集字节跳动抖音近期商业发展信息")
        assert "product_improvement" not in out
        assert "收集字节跳动抖音近期商业发展信息" in out
