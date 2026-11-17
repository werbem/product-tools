"""Competitor peer relations — Memory union merge, listing resolve, bidirectional edges."""

from __future__ import annotations

from app.application.services.intent_entities import (
    looks_like_competitor_listing_query,
    resolve_competitor_suggestions,
    suggest_default_competitors,
)
from app.application.services.memory_writer import MemoryWriter
from app.domain.entities.project_memory import (
    PeerEdge,
    ProjectMemory,
    ProjectMemoryEntities,
    lookup_peers,
    upsert_peer_edges,
)
from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore


def test_competitors_merge_is_union():
    base = ProjectMemoryEntities(
        our_company="饿了么",
        competitors=["美团"],
        product="外卖",
    )
    nxt = ProjectMemoryEntities(
        our_company="饿了么",
        competitors=["抖音外卖"],
        product="外卖",
    )
    merged = base.merge_nonempty(nxt)
    assert merged.competitors == ["美团", "抖音外卖"]


def test_merge_sanitizes_placeholders():
    base = ProjectMemoryEntities(our_company="饿了么", competitors=["美团"], product="外卖")
    nxt = ProjectMemoryEntities(
        our_company="饿了么",
        competitors=["公开市场与主要竞品", "竞品公司", "京东外卖"],
        product="外卖",
    )
    merged = base.merge_nonempty(nxt)
    assert "京东外卖" in merged.competitors
    assert "公开市场与主要竞品" not in merged.competitors
    assert "竞品公司" not in merged.competitors


def test_resolve_prefers_memory_over_curated_only_when_present(tmp_path):
    store = ProjectMemoryStore(base_dir=tmp_path)
    writer = MemoryWriter(store=store)
    writer.upsert_from_deep_success(
        project_id="p1",
        conversation_id="c1",
        task_id="t1",
        our_company="饿了么",
        competitor_company="美团",
        product="外卖",
        competitors=["美团"],
        markdown="# 摘要\n结论一句。",
    )
    memory = store.get("p1")
    assert memory is not None
    pack = resolve_competitor_suggestions("饿了么", "外卖", memory)
    assert "美团" in pack["peers"]
    assert pack["question_mode"] in {"memory_peers", "mixed_peers"}
    assert pack["peers"][0] == "美团"


def test_resolve_falls_back_to_curated_without_memory():
    pack = resolve_competitor_suggestions("饿了么", "外卖", None)
    assert "美团" in pack["peers"]
    assert pack["question_mode"] == "curated_peers"


def test_peer_edges_bidirectional_lookup(tmp_path):
    store = ProjectMemoryStore(base_dir=tmp_path)
    writer = MemoryWriter(store=store)
    writer.upsert_from_deep_success(
        project_id="p2",
        conversation_id="c2",
        task_id="t2",
        our_company="饿了么",
        competitor_company="美团",
        product="外卖",
        competitors=["美团"],
    )
    memory = store.get("p2")
    assert memory is not None
    assert lookup_peers(memory, "饿了么", "外卖") == ["美团"]
    assert "饿了么" in lookup_peers(memory, "美团", "外卖")


def test_peer_edges_product_isolation():
    memory = ProjectMemory.empty("p3")
    memory.peer_edges = upsert_peer_edges(
        [],
        company="美团",
        competitors=["饿了么"],
        product="外卖",
        source_task_id="t1",
        source_type="report",
    )
    memory.peer_edges = upsert_peer_edges(
        memory.peer_edges,
        company="美团",
        competitors=["携程"],
        product="酒店",
        source_task_id="t2",
        source_type="report",
    )
    assert lookup_peers(memory, "美团", "外卖") == ["饿了么"]
    assert lookup_peers(memory, "美团", "酒店") == ["携程"]
    # No product → both ok
    both = lookup_peers(memory, "美团", None)
    assert "饿了么" in both and "携程" in both


def test_record_peer_relations_on_launch(tmp_path):
    store = ProjectMemoryStore(base_dir=tmp_path)
    writer = MemoryWriter(store=store)
    out = writer.record_peer_relations(
        project_id="p4",
        company="飞猪",
        competitors=["美团", "携程"],
        product="酒店",
        source_task_id="launch-1",
        source_type="user",
    )
    assert out is not None
    loaded = store.get("p4")
    assert loaded is not None
    assert "美团" in loaded.entities.competitors
    assert "飞猪" in lookup_peers(loaded, "携程", "酒店")


def test_listing_query_detects_dou():
    assert looks_like_competitor_listing_query("饿了么的外卖竞品公司都有哪些？")


def test_peer_edge_normalize_and_roundtrip():
    pair = PeerEdge.normalize_pair("美团", "饿了么")
    assert pair is not None
    a, b = pair
    edge = PeerEdge(a=a, b=b, product="外卖", source_type="report")
    restored = PeerEdge.from_dict(edge.to_dict())
    assert restored is not None
    assert restored.a == a and restored.b == b
    assert restored.product == "外卖"
