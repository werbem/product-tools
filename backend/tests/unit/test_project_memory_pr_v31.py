"""Phase 3 V3.1: ProjectMemory store, writer, Intent/follow_up consumption, API."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.report_dto import ReportCreateRequest
from app.application.services.conversation_service import ConversationService
from app.application.services.follow_up_service import FollowUpService
from app.application.services.memory_service import MemoryService
from app.application.services.memory_writer import MemoryWriter
from app.application.services.project_service import ProjectService
from app.domain.entities.project_memory import (
    MAX_FINDING_CHARS,
    MAX_KEY_FINDINGS,
    MemoryFinding,
    ProjectMemory,
    ProjectMemoryEntities,
    format_memory_prompt_block,
)
from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore
from app.infrastructure.persistence.copilot.stores import ProjectStore


@pytest.fixture
def persistence(tmp_path: Path, monkeypatch):
    data = tmp_path / "persistence"
    data.mkdir()
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.stores.DATA_DIR",
        data,
    )
    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.project_memory_store.DATA_DIR",
        data,
    )
    return data


class TestProjectMemoryStore:
    def test_crud_and_empty(self, persistence: Path) -> None:
        store = ProjectMemoryStore(base_dir=persistence)
        assert store.get("p1") is None
        empty = store.get_or_empty("p1")
        assert empty.project_id == "p1"
        assert empty.entities.our_company is None

        mem = ProjectMemory(
            project_id="p1",
            entities=ProjectMemoryEntities(
                our_company="飞猪",
                competitors=["美团"],
                product="酒店",
            ),
            key_findings=[
                MemoryFinding(text="会员转化弱于竞品", source_type="report"),
            ],
            last_workflow_type="competitive_analysis",
        )
        store.upsert(mem)
        loaded = store.get("p1")
        assert loaded is not None
        assert loaded.entities.our_company == "飞猪"
        assert loaded.key_findings[0].text.startswith("会员")

        store.delete("p1")
        assert store.get("p1") is None

    def test_enforce_limits(self, persistence: Path) -> None:
        store = ProjectMemoryStore(base_dir=persistence)
        findings = [
            MemoryFinding(text=("x" * 300) + f"-{i}", source_type="manual")
            for i in range(15)
        ]
        mem = ProjectMemory(
            project_id="p2",
            key_findings=findings,
            last_objectives=[f"obj-{i}" for i in range(10)],
            open_questions=[f"q-{i}" for i in range(10)],
        )
        saved = store.upsert(mem)
        assert len(saved.key_findings) == MAX_KEY_FINDINGS
        assert all(len(f.text) <= MAX_FINDING_CHARS for f in saved.key_findings)
        assert len(saved.last_objectives) <= 5
        assert len(saved.open_questions) <= 5

    def test_concurrent_upserts_single_process(self, persistence: Path) -> None:
        store = ProjectMemoryStore(base_dir=persistence)
        errors: list[BaseException] = []

        def _write(i: int) -> None:
            try:
                mem = store.get_or_empty("p-concurrent")
                mem.entities.our_company = f"公司{i}"
                mem.key_findings = [
                    MemoryFinding(text=f"finding-{i}", source_type="manual"),
                ]
                store.upsert(mem)
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=_write, args=(i,)) for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        final = store.get("p-concurrent")
        assert final is not None
        assert final.entities.our_company is not None


class TestMemoryWriter:
    def test_deep_success_updates_entities_and_findings(self, persistence: Path) -> None:
        store = ProjectMemoryStore(base_dir=persistence)
        writer = MemoryWriter(store=store)
        md = (
            "# 执行摘要\n飞猪在会员权益上落后美团。\n\n"
            "# 风险\n价格战压力上升。\n\n"
            "# 机会\n差旅场景可突破。\n"
        )
        result = writer.upsert_from_deep_success(
            project_id="proj-a",
            conversation_id="conv-1",
            task_id="task-1",
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="product_improvement",
            scene="对比会员体系",
            markdown=md,
            sections=[
                {"title": "执行摘要", "content": "飞猪在会员权益上落后美团。"},
                {"title": "风险", "content": "价格战压力上升。"},
            ],
        )
        assert result is not None
        loaded = store.get("proj-a")
        assert loaded is not None
        assert loaded.entities.our_company == "飞猪"
        assert "美团" in loaded.entities.competitors
        assert loaded.entities.product == "酒店"
        assert loaded.last_workflow_type == "competitive_analysis"
        assert loaded.last_task_id == "task-1"
        assert len(loaded.key_findings) >= 2
        assert "conv-1" in loaded.conversation_summaries

    def test_collection_success_without_validated_input(self, persistence: Path) -> None:
        store = ProjectMemoryStore(base_dir=persistence)
        writer = MemoryWriter(store=store)
        result = writer.upsert_from_collection_success(
            project_id="proj-b",
            conversation_id="conv-c",
            task_id="collect-1",
            our_company="字节跳动",
            product="抖音",
            topic="短视频电商近期动态",
            evidence_titles=["某媒体：抖音电商 GMV 增长", "行业报告：直播带货"],
        )
        assert result is not None
        loaded = store.get("proj-b")
        assert loaded is not None
        assert loaded.entities.our_company == "字节跳动"
        assert loaded.last_collection_id == "collect-1"
        assert loaded.last_workflow_type == "research"
        assert any("收集主题" in f.text for f in loaded.key_findings)

    def test_writer_exception_swallowed(self, persistence: Path) -> None:
        store = ProjectMemoryStore(base_dir=persistence)
        writer = MemoryWriter(store=store)
        # Corrupt by replacing upsert to raise
        store.upsert = MagicMock(side_effect=RuntimeError("disk full"))  # type: ignore[method-assign]
        out = writer.upsert_from_deep_success(
            project_id="proj-x",
            conversation_id=None,
            task_id="t",
            our_company="A",
            competitor_company="B",
            product="P",
            markdown="# Hi\nhello",
        )
        assert out is None


class TestDeepLauncherMemoryHook:
    @pytest.mark.asyncio
    async def test_writer_failure_does_not_break_finalize(self, persistence: Path) -> None:
        from app.application.services.workflow_launcher import DeepAnalysisWorkflowLauncher

        bad_writer = MagicMock()
        bad_writer.upsert_from_deep_success.side_effect = RuntimeError("boom")
        launcher = DeepAnalysisWorkflowLauncher(memory_writer=bad_writer)
        entry = {
            "project_id": "p1",
            "conversation_id": "c1",
            "status": "completed",
        }
        body = ReportCreateRequest(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="product_improvement",
        )
        # Should not raise
        launcher._write_project_memory(entry, "task-1", body, {"markdown": "# x\ny", "sections": []})
        assert bad_writer.upsert_from_deep_success.called


class TestIntentMemoryFill:
    def test_merge_memory_partial_fills_empty(self) -> None:
        memory = ProjectMemory(
            project_id="p",
            entities=ProjectMemoryEntities(
                our_company="飞猪",
                competitors=["美团"],
                product="酒店",
            ),
            last_objectives=["会员对比"],
        )
        merged = ConversationService._merge_memory_partial(
            None,
            memory,
            raw_message="继续分析，重点看会员",
        )
        assert merged is not None
        assert merged.company == "飞猪"
        assert merged.competitors == ["美团"]
        assert merged.product == "酒店"

    def test_fill_intent_from_memory_user_priority(self) -> None:
        memory = ProjectMemory(
            project_id="p",
            entities=ProjectMemoryEntities(
                our_company="飞猪",
                competitors=["美团"],
                product="酒店",
            ),
        )
        intent = IntentUnderstandingResult(
            type="competitive_analysis",
            company=None,
            competitors=[],
            product=None,
            objective=None,
            confidence=0.5,
            needs_clarification=True,
            missing_fields=["company", "product"],
            raw_message="继续分析酒店",
        )
        filled = ConversationService._fill_intent_from_memory(intent, memory)
        assert filled.company == "飞猪"
        assert filled.product == "酒店"
        assert filled.competitors == ["美团"]
        assert filled.needs_clarification is False


class TestFollowUpMemoryFirst:
    @pytest.mark.asyncio
    async def test_context_prefers_memory_findings(self) -> None:
        memory = ProjectMemory(
            project_id="p",
            entities=ProjectMemoryEntities(
                our_company="飞猪",
                competitors=["美团"],
                product="酒店",
            ),
            key_findings=[
                MemoryFinding(text="会员转化弱于美团", source_type="report"),
            ],
        )
        svc = FollowUpService(llm_generate=AsyncMock(return_value=MagicMock(content="答：历史风险…")))
        result = await svc.handle(
            query="基于上次结论，风险有哪些？",
            intent=IntentUnderstandingResult(
                type="competitive_analysis",
                company=None,
                competitors=[],
                product=None,
                confidence=0.4,
                needs_clarification=False,
                raw_message="基于上次结论，风险有哪些？",
            ),
            messages=[],
            conversation_id="new-conv",
            project_memory=memory,
        )
        assert result.follow_up_mode == "short_answer"
        assert "会员转化" in result.context_summary or "关键结论" in result.context_summary
        assert "项目记忆" in result.context_summary


class TestMemoryAcrossConversations:
    def test_new_session_reads_prior_memory(self, persistence: Path) -> None:
        store = ProjectMemoryStore(base_dir=persistence)
        writer = MemoryWriter(store=store)
        writer.upsert_from_deep_success(
            project_id="proj-a",
            conversation_id="conv-1",
            task_id="t1",
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            markdown="# 摘要\n会员是关键差距。\n",
        )
        # New conversation same project
        loaded = store.get("proj-a")
        assert loaded is not None
        partial = ConversationService._merge_memory_partial(
            None,
            loaded,
            raw_message="继续分析，重点看会员",
        )
        assert partial is not None
        assert partial.company == "飞猪"
        block = format_memory_prompt_block(loaded)
        assert "飞猪" in block


class TestMemoryAPI:
    def _clear_caches(self) -> None:
        from app.interfaces.api.dependencies.copilot import (
            get_conversation_store,
            get_intent_understanding_service,
            get_knowledge_notes_store,
            get_knowledge_service,
            get_memory_service,
            get_message_store,
            get_project_memory_store,
            get_project_service,
            get_project_store,
        )
        from app.interfaces.api.dependencies.workflow import (
            get_artifact_store,
            get_collection_workflow_launcher,
            get_workflow_launcher,
        )

        for fn in (
            get_project_store,
            get_conversation_store,
            get_message_store,
            get_intent_understanding_service,
            get_project_memory_store,
            get_memory_service,
            get_knowledge_notes_store,
            get_knowledge_service,
            get_project_service,
            get_artifact_store,
            get_collection_workflow_launcher,
            get_workflow_launcher,
        ):
            if hasattr(fn, "cache_clear"):
                fn.cache_clear()

    def test_get_empty_skeleton_and_patch(self, persistence: Path, monkeypatch) -> None:
        monkeypatch.setenv("APP_DATA_DIR", str(persistence.parent))
        self._clear_caches()
        from app.main import app

        client = TestClient(app)
        try:
            created = client.post("/api/projects", json={"title": "Memory Proj"}).json()
            pid = created["id"]
            get_resp = client.get(f"/api/projects/{pid}/memory")
            assert get_resp.status_code == 200
            body = get_resp.json()
            assert body["project_id"] == pid
            assert body["entities"]["our_company"] is None
            assert body["key_findings"] == []

            patch = client.patch(
                f"/api/projects/{pid}/memory",
                json={
                    "entities": {
                        "our_company": "飞猪",
                        "competitors": ["美团"],
                        "product": "酒店",
                    },
                    "open_questions": ["会员留存如何？"],
                },
            )
            assert patch.status_code == 200
            patched = patch.json()
            assert patched["entities"]["our_company"] == "飞猪"
            assert patched["open_questions"] == ["会员留存如何？"]

            missing = client.get("/api/projects/no-such/memory")
            assert missing.status_code == 404
        finally:
            app.dependency_overrides.clear()
            self._clear_caches()


class TestMemoryService:
    def test_patch_requires_project(self, persistence: Path) -> None:
        projects = ProjectStore()
        memory_store = ProjectMemoryStore(base_dir=persistence)
        svc = MemoryService(memory_store=memory_store, project_store=projects)
        from app.application.exceptions import ProjectNotFoundError

        with pytest.raises(ProjectNotFoundError):
            svc.get_memory("missing")
