"""Phase 3 V3.2: Knowledge Notes CRUD, search, and prompt injection."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.testclient import TestClient

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.report_dto import ReportCreateRequest
from app.application.exceptions import KnowledgeNoteNotFoundError, ProjectNotFoundError
from app.application.services.conversation_service import ConversationService
from app.application.services.follow_up_service import FollowUpService
from app.application.services.knowledge_service import KnowledgeService
from app.application.services.simple_query_service import SimpleQueryService
from app.domain.entities.knowledge_note import (
    KNOWLEDGE_PROMPT_PREFIX,
    KnowledgeNote,
    format_knowledge_prompt_block,
    notes_to_optional_dict,
    score_note,
)
from app.infrastructure.persistence.copilot.knowledge_notes_store import KnowledgeNotesStore
from app.infrastructure.persistence.copilot.stores import ProjectStore, new_id


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
        "app.infrastructure.persistence.copilot.knowledge_notes_store.DATA_DIR",
        data,
    )
    monkeypatch.setattr(
        "app.infrastructure.persistence.copilot.project_memory_store.DATA_DIR",
        data,
    )
    return data


def _projects(persistence: Path) -> ProjectStore:
    return ProjectStore()


class TestKnowledgeNotesStore:
    def test_crud_and_project_isolation(self, persistence: Path) -> None:
        store = KnowledgeNotesStore(base_dir=persistence)
        a = KnowledgeNote(
            id=new_id(),
            project_id="proj-a",
            title="飞猪酒店会员",
            body="重点关注积分互通与佣金",
            tags=["会员", "酒店"],
        )
        b = KnowledgeNote(
            id=new_id(),
            project_id="proj-b",
            title="美团外卖",
            body="补贴与履约",
            tags=["外卖"],
        )
        store.create(a)
        store.create(b)
        listed = store.list_by_project("proj-a")
        assert len(listed) == 1
        assert listed[0].title == "飞猪酒店会员"
        hits = store.search("proj-a", "会员", limit=5)
        assert len(hits) == 1
        assert hits[0].id == a.id
        assert store.search("proj-b", "会员", limit=5) == []
        assert store.search("proj-a", "外卖", limit=5) == []

        a.body = "更新后的佣金结构"
        store.update(a)
        assert store.get(a.id).body.startswith("更新")
        assert store.delete(a.id) is True
        assert store.get(a.id) is None

    def test_score_title_body_tags(self) -> None:
        note = KnowledgeNote(
            id="n1",
            project_id="p",
            title="酒店会员体系",
            body="关注积分互通",
            tags=["佣金"],
        )
        assert score_note(note, "会员") > 0
        assert score_note(note, "积分") > 0
        assert score_note(note, "佣金") > 0
        assert score_note(note, "无关词xyz") == 0


class TestKnowledgeService:
    def test_create_requires_project(self, persistence: Path) -> None:
        projects = _projects(persistence)
        svc = KnowledgeService(
            notes_store=KnowledgeNotesStore(base_dir=persistence),
            project_store=projects,
        )
        with pytest.raises(ProjectNotFoundError):
            svc.create_note("missing", title="t", body="b")

    def test_crud_via_service(self, persistence: Path) -> None:
        from app.domain.entities.analysis_project import AnalysisProject
        from app.domain.entities.copilot_common import utc_now

        projects = _projects(persistence)
        now = utc_now()
        proj = projects.create_project(
            AnalysisProject(
                id=new_id(),
                title="K Proj",
                objective=None,
                status="active",
                created_at=now,
                updated_at=now,
                metadata={},
            ),
        )
        svc = KnowledgeService(
            notes_store=KnowledgeNotesStore(base_dir=persistence),
            project_store=projects,
        )
        note = svc.create_note(
            proj.id,
            title="飞猪酒店会员",
            body="重点关注积分互通与佣金",
            tags=["会员"],
        )
        assert svc.get_note(proj.id, note.id).title == "飞猪酒店会员"
        hits = svc.search(proj.id, "会员")
        assert hits[0].id == note.id
        svc.update_note(proj.id, note.id, {"body": "新内容：积分互通"})
        assert "新内容" in svc.get_note(proj.id, note.id).body
        svc.delete_note(proj.id, note.id)
        with pytest.raises(KnowledgeNoteNotFoundError):
            svc.get_note(proj.id, note.id)


class TestKnowledgePromptInjection:
    def test_format_prefix_and_limits(self) -> None:
        notes = [
            KnowledgeNote(
                id="1",
                project_id="p",
                title="飞猪酒店会员",
                body="重点关注积分互通与佣金" * 50,
                tags=["会员"],
            ),
        ]
        block = format_knowledge_prompt_block(notes, limit=1200)
        assert KNOWLEDGE_PROMPT_PREFIX in block
        assert len(block) <= 1200
        blob = notes_to_optional_dict(notes)
        assert blob is not None
        assert "prompt_block" in blob
        assert blob["notes"][0]["title"] == "飞猪酒店会员"

    def test_attach_knowledge_optional_on_deep_request(self) -> None:
        notes = [
            KnowledgeNote(
                id="1",
                project_id="p",
                title="飞猪酒店会员",
                body="重点关注积分互通与佣金",
                tags=["会员"],
            ),
        ]
        req = ReportCreateRequest(
            our_company="飞猪",
            competitor_company="美团",
            product="酒店",
            objective="product_improvement",
        )
        out = ConversationService._attach_knowledge_optional(req, notes)
        optional = out.optional or {}
        assert "knowledge_notes" in optional
        assert optional["knowledge_notes"]["notes"][0]["title"] == "飞猪酒店会员"
        assert KNOWLEDGE_PROMPT_PREFIX in optional["knowledge_notes"]["prompt_block"]

    @pytest.mark.asyncio
    async def test_follow_up_context_includes_notes_prefix(self) -> None:
        block = format_knowledge_prompt_block(
            [
                KnowledgeNote(
                    id="1",
                    project_id="p",
                    title="飞猪酒店会员",
                    body="重点关注积分互通与佣金",
                    tags=["会员"],
                ),
            ],
        )
        svc = FollowUpService(
            llm_generate=AsyncMock(return_value=MagicMock(content="内部笔记：积分互通…")),
        )
        result = await svc.handle(
            query="会员体系有什么注意点？",
            intent=IntentUnderstandingResult(
                type="competitive_analysis",
                company="飞猪",
                competitors=["美团"],
                product="酒店",
                confidence=0.8,
                needs_clarification=False,
                raw_message="会员体系有什么注意点？",
            ),
            messages=[],
            conversation_id="c1",
            knowledge_notes_block=block,
        )
        assert result.follow_up_mode == "short_answer"
        assert KNOWLEDGE_PROMPT_PREFIX in result.context_summary

    @pytest.mark.asyncio
    async def test_query_summarize_includes_notes(self) -> None:
        from app.application.services.simple_query_service import QuerySource

        captured: dict = {}

        async def fake_llm(*, system_prompt, user_prompt, temperature=0.3):
            captured["user_prompt"] = user_prompt
            return MagicMock(content="答：注意积分互通（内部笔记）")

        svc = SimpleQueryService(llm_generate=fake_llm)
        text = await svc._summarize(
            query="会员注意点",
            sources=[
                QuerySource(title="公开源", url="https://example.com", snippet="x"),
            ],
            knowledge_notes_block=format_knowledge_prompt_block(
                [
                    KnowledgeNote(
                        id="1",
                        project_id="p",
                        title="飞猪酒店会员",
                        body="重点关注积分互通与佣金",
                    ),
                ],
            ),
        )
        assert "内部笔记" in text or "积分" in text
        assert KNOWLEDGE_PROMPT_PREFIX in captured["user_prompt"]

    def test_research_optional_notes_not_evidence_shape(self) -> None:
        """Notes ride optional only — never Evidence ID shaped."""
        blob = notes_to_optional_dict(
            [
                KnowledgeNote(
                    id="note-1",
                    project_id="p",
                    title="主题关注",
                    body="佣金与积分",
                ),
            ],
        )
        assert blob is not None
        assert "evidence_items" not in blob
        assert all(not str(n.get("id", "")).startswith("E") for n in blob["notes"])


class TestKnowledgeAPI:
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

    def test_api_crud_and_search(self, persistence: Path, monkeypatch) -> None:
        monkeypatch.setenv("APP_DATA_DIR", str(persistence.parent))
        self._clear_caches()
        from app.main import app

        client = TestClient(app)
        try:
            pid = client.post("/api/projects", json={"title": "Know Proj"}).json()["id"]
            created = client.post(
                f"/api/projects/{pid}/knowledge/notes",
                json={
                    "title": "飞猪酒店会员",
                    "body": "重点关注积分互通与佣金",
                    "tags": ["会员", "酒店"],
                },
            )
            assert created.status_code == 201, created.text
            note = created.json()
            nid = note["id"]

            listed = client.get(f"/api/projects/{pid}/knowledge/notes")
            assert listed.status_code == 200
            assert len(listed.json()) == 1

            got = client.get(f"/api/projects/{pid}/knowledge/notes/{nid}")
            assert got.status_code == 200

            search = client.get(
                f"/api/projects/{pid}/knowledge/search",
                params={"q": "会员", "limit": 5},
            )
            assert search.status_code == 200
            assert search.json()[0]["id"] == nid

            patched = client.patch(
                f"/api/projects/{pid}/knowledge/notes/{nid}",
                json={"body": "积分互通 + 佣金率"},
            )
            assert patched.status_code == 200
            assert "佣金率" in patched.json()["body"]

            # isolation: other project cannot see note
            pid2 = client.post("/api/projects", json={"title": "Other"}).json()["id"]
            assert client.get(
                f"/api/projects/{pid2}/knowledge/notes/{nid}",
            ).status_code == 404
            assert client.get(
                f"/api/projects/{pid2}/knowledge/search",
                params={"q": "会员"},
            ).json() == []

            deleted = client.delete(f"/api/projects/{pid}/knowledge/notes/{nid}")
            assert deleted.status_code == 204
            assert client.get(
                f"/api/projects/{pid}/knowledge/notes/{nid}",
            ).status_code == 404
        finally:
            app.dependency_overrides.clear()
            self._clear_caches()
