"""Phase 4: body dates, undated cap, G3 routing, hybrid knowledge/memory retrieval."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.hybrid_retrieval import fuse_scores
from app.application.services.intent_mapper import (
    collection_primary_over_nested_analysis,
    resolve_workflow_kind,
)
from app.application.services.knowledge_service import KnowledgeService
from app.application.services.memory_findings_index import MemoryFindingsIndex, finding_vector_id
from app.domain.entities.analysis_project import AnalysisProject
from app.domain.entities.knowledge_note import KnowledgeNote, score_note
from app.domain.entities.project_memory import MemoryFinding, ProjectMemory, ProjectMemoryEntities
from app.infrastructure.agents.report_prompt import build_report_prompt
from app.infrastructure.llm.embedding_client import cosine_similarity
from app.infrastructure.persistence.copilot.knowledge_notes_store import KnowledgeNotesStore
from app.infrastructure.persistence.copilot.stores import ProjectStore
from app.infrastructure.persistence.copilot.vector_store import VectorJsonStore
from app.infrastructure.tools.evidence_freshness import extract_published_date_from_html


class TestBodyDateExtraction:
    def test_body_date_when_no_meta(self):
        html = "<html><body><p>发布于2025年1月15日的评测</p></body></html>"
        parsed, source = extract_published_date_from_html(html)
        assert parsed == "2025-01-15"
        assert source == "page_body"


class TestG3CollectionPrimary:
    def test_collect_report_materials_is_collection(self):
        raw = "帮我收集竞品分析报告相关资料"
        assert collection_primary_over_nested_analysis(raw)
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company="竞品",
            competitors=[],
            product="资料",
            objective="intelligence_collection",
            confidence=0.8,
            raw_message=raw,
        )
        assert resolve_workflow_kind(intent, raw) == "intelligence_collection"

    def test_vs_plus_collect_still_deep(self):
        raw = "分析飞猪 vs 美团，并收集相关公开资料做支撑"
        assert not collection_primary_over_nested_analysis(raw)
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company="飞猪",
            competitors=["美团"],
            product="酒店",
            confidence=0.9,
            raw_message=raw,
        )
        assert resolve_workflow_kind(intent, raw) == "deep_analysis"


class TestCompareStubBanner:
    def test_gap_stub_mentions_incomplete_compare(self):
        prompt = build_report_prompt(
            "A", "B", "P", "product_improvement",
            evidence_json="[]",
            gap_json="{}",
            strategy_json="{}",
            gap_is_stub=True,
            fast_mode=False,
        )
        assert "对比未完整" in prompt


class TestHybridFusion:
    def test_fuse_prefers_vector_when_kw_empty(self):
        fused = fuse_scores({}, {"n1": 0.9, "n2": 0.1})
        assert fused["n1"] > fused["n2"]

    def test_cosine(self):
        assert cosine_similarity([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)
        assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0)


class TestKnowledgeHybridSearch:
    def test_vector_hit_without_keyword(self, tmp_path: Path):
        projects = ProjectStore(base_dir=tmp_path)
        notes = KnowledgeNotesStore(base_dir=tmp_path)
        vectors = VectorJsonStore("knowledge_note_vectors.json", base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        proj = AnalysisProject(
            id="p1",
            title="t",
            objective="o",
            status="active",
            created_at=now,
            updated_at=now,
        )
        projects.create_project(proj)
        note = KnowledgeNote(
            id="n1",
            project_id="p1",
            title="飞猪酒店会员",
            body="积分互通与佣金压力较大",
            tags=["会员"],
            created_at=now,
            updated_at=now,
        )
        notes.create(note)
        # Stub embedding space: note → [1,0], synonym query → near [1,0]
        vectors.upsert("n1", [1.0, 0.0], model="stub", project_id="p1")

        class StubEmbed:
            model = "stub"

            async def embed(self, text: str):
                if "忠诚度" in text or "会员" in text:
                    return [0.99, 0.01]
                return [0.0, 1.0]

            @property
            def available(self) -> bool:
                return True

        svc = KnowledgeService(
            notes_store=notes,
            project_store=projects,
            vector_store=vectors,
            embedding_client=StubEmbed(),  # type: ignore[arg-type]
        )
        # Query has no lexical overlap with title/body except via vector synonym path
        # "用户忠诚度计划" won't match 积分/佣金 keyword strongly — force kw miss
        q = "用户忠诚度计划"
        assert score_note(note, q) == 0.0
        hits = asyncio.run(svc.search_async("p1", q, limit=3))
        assert hits and hits[0].id == "n1"

    def test_keyword_fallback_when_embed_unavailable(self, tmp_path: Path):
        projects = ProjectStore(base_dir=tmp_path)
        notes = KnowledgeNotesStore(base_dir=tmp_path)
        now = datetime.now(timezone.utc)
        projects.create_project(
            AnalysisProject(
                id="p1", title="t", objective="o", status="active",
                created_at=now, updated_at=now,
            )
        )
        note = KnowledgeNote(
            id="n1", project_id="p1", title="飞猪酒店会员",
            body="积分互通", tags=[], created_at=now, updated_at=now,
        )
        notes.create(note)

        class DeadEmbed:
            model = "x"

            async def embed(self, text: str):
                return None

            @property
            def available(self) -> bool:
                return False

        svc = KnowledgeService(
            notes_store=notes,
            project_store=projects,
            vector_store=VectorJsonStore("knowledge_note_vectors.json", base_dir=tmp_path),
            embedding_client=DeadEmbed(),  # type: ignore[arg-type]
        )
        hits = asyncio.run(svc.search_async("p1", "会员", limit=3))
        assert hits and hits[0].id == "n1"


class TestMemoryFindingsRank:
    def test_rank_by_stub_vectors(self, tmp_path: Path):
        store = VectorJsonStore("project_memory_vectors.json", base_dir=tmp_path)
        memory = ProjectMemory(
            project_id="p1",
            entities=ProjectMemoryEntities(our_company="飞猪"),
            key_findings=[
                MemoryFinding(text="价格战加剧"),
                MemoryFinding(text="会员转化弱于美团"),
            ],
        )
        fid = finding_vector_id("p1", "会员转化弱于美团")
        store.upsert(fid, [1.0, 0.0], model="stub", project_id="p1")

        class StubEmbed:
            model = "stub"

            async def embed(self, text: str):
                return [1.0, 0.0]

            @property
            def available(self) -> bool:
                return True

        idx = MemoryFindingsIndex(vector_store=store, embedding_client=StubEmbed())  # type: ignore[arg-type]
        ranked = asyncio.run(idx.rank_findings(memory, "会员体系风险", limit=2))
        assert ranked[0].text.startswith("会员")
