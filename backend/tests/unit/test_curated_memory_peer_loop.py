"""Curated catalog + Memory peer persist loop (no web on listing)."""

from __future__ import annotations

from app.application.services.intent_entities import (
    infer_default_product,
    resolve_competitor_suggestions,
    suggest_default_competitors,
)
from app.application.services.memory_writer import MemoryWriter
from app.domain.entities.project_memory import lookup_peers
from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore


def test_curated_covers_common_verticals() -> None:
    assert "快手" in suggest_default_competitors("抖音", "短视频")
    assert "抖音" not in suggest_default_competitors("抖音", None)
    assert "淘宝" in suggest_default_competitors("拼多多", None)
    assert "美团" in suggest_default_competitors("饿了么", "外卖")
    assert "高德打车" in suggest_default_competitors("滴滴", None)
    assert "微信支付" in suggest_default_competitors("支付宝", None)
    assert "钉钉" in suggest_default_competitors("飞书", None)
    assert "QQ音乐" in suggest_default_competitors("网易云音乐", None)


def test_parent_company_falls_back_to_product_brand() -> None:
    peers = suggest_default_competitors("字节跳动", "抖音")
    assert peers
    assert "抖音" not in peers
    assert "快手" in peers or "小红书" in peers
    assert infer_default_product("字节跳动") == "抖音"


def test_listing_curated_persists_then_memory_hits(tmp_path) -> None:
    store = ProjectMemoryStore(base_dir=tmp_path)
    writer = MemoryWriter(store=store)

    first = resolve_competitor_suggestions("抖音", "短视频", None)
    assert first["question_mode"] == "curated_peers"
    assert first["peers"]

    writer.record_peer_relations(
        project_id="p-loop",
        company="抖音",
        competitors=list(first["peers"]),
        product="短视频",
        source_type="curated",
    )
    memory = store.get("p-loop")
    assert memory is not None
    assert lookup_peers(memory, "抖音", "短视频")

    second = resolve_competitor_suggestions("抖音", "短视频", memory)
    assert second["peers"][0] == first["peers"][0]
    assert second["question_mode"] in {"memory_peers", "mixed_peers"}
    assert "memory" in second["sources"]
    # Bidirectional: 快手 should see 抖音
    assert "抖音" in lookup_peers(memory, first["peers"][0], "短视频")


def test_empty_unknown_brand_stays_empty_without_web() -> None:
    pack = resolve_competitor_suggestions("某不知名小厂XYZ", None, None)
    assert pack["peers"] == []
    assert pack["question_mode"] == "empty"
