"""Knowledge Notes application service (CRUD + hybrid search)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.application.exceptions import KnowledgeNoteNotFoundError, ProjectNotFoundError
from app.application.services.hybrid_retrieval import (
    fuse_scores,
    rank_by_fused,
    vector_scores_for_query,
)
from app.domain.entities.copilot_common import utc_now
from app.domain.entities.knowledge_note import (
    DEFAULT_INJECT_TOP_K,
    DEFAULT_SEARCH_LIMIT,
    MAX_NOTES_PER_PROJECT,
    KnowledgeNote,
    format_knowledge_prompt_block,
    notes_to_optional_dict,
    score_note,
)
from app.infrastructure.llm.embedding_client import EmbeddingClient
from app.infrastructure.persistence.copilot.knowledge_notes_store import KnowledgeNotesStore
from app.infrastructure.persistence.copilot.stores import ProjectStore, new_id
from app.infrastructure.persistence.copilot.vector_store import VectorJsonStore

logger = logging.getLogger(__name__)


def _run_coro(coro):  # type: ignore[no-untyped-def]
    """Run coroutine from sync FastAPI handlers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Nested loop (tests): run in a fresh loop via thread is overkill — keyword path
    raise RuntimeError("cannot nest asyncio.run; use async API")


class KnowledgeService:
    def __init__(
        self,
        notes_store: KnowledgeNotesStore | None = None,
        project_store: ProjectStore | None = None,
        vector_store: VectorJsonStore | None = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._notes = notes_store or KnowledgeNotesStore()
        self._projects = project_store or ProjectStore()
        self._vectors = vector_store or VectorJsonStore("knowledge_note_vectors.json")
        self._embed = embedding_client or EmbeddingClient()

    def _require_project(self, project_id: str) -> None:
        if not self._projects.get_project(project_id):
            raise ProjectNotFoundError(project_id)

    def list_notes(self, project_id: str) -> list[KnowledgeNote]:
        self._require_project(project_id)
        return self._notes.list_by_project(project_id)

    def get_note(self, project_id: str, note_id: str) -> KnowledgeNote:
        self._require_project(project_id)
        note = self._notes.get(note_id)
        if not note or note.project_id != project_id:
            raise KnowledgeNoteNotFoundError(note_id)
        return note

    def create_note(
        self,
        project_id: str,
        *,
        title: str,
        body: str,
        tags: list[str] | None = None,
    ) -> KnowledgeNote:
        self._require_project(project_id)
        if self._notes.count_by_project(project_id) >= MAX_NOTES_PER_PROJECT:
            raise ValueError(f"每个项目最多 {MAX_NOTES_PER_PROJECT} 条知识笔记")
        title = (title or "").strip()
        body = (body or "").strip()
        if not title:
            raise ValueError("title must not be empty")
        if not body:
            raise ValueError("body must not be empty")
        now = utc_now()
        note = KnowledgeNote(
            id=new_id(),
            project_id=project_id,
            title=title,
            body=body,
            tags=list(tags or []),
            created_at=now,
            updated_at=now,
        )
        created = self._notes.create(note)
        self._schedule_embed(created)
        return created

    def update_note(
        self,
        project_id: str,
        note_id: str,
        patch: dict[str, Any],
    ) -> KnowledgeNote:
        note = self.get_note(project_id, note_id)
        if "title" in patch and patch["title"] is not None:
            title = str(patch["title"]).strip()
            if not title:
                raise ValueError("title must not be empty")
            note.title = title
        if "body" in patch and patch["body"] is not None:
            body = str(patch["body"]).strip()
            if not body:
                raise ValueError("body must not be empty")
            note.body = body
        if "tags" in patch and patch["tags"] is not None:
            if not isinstance(patch["tags"], list):
                raise ValueError("tags must be a list")
            note.tags = [str(t) for t in patch["tags"]]
        note.updated_at = utc_now()
        updated = self._notes.update(note)
        self._schedule_embed(updated)
        return updated

    def delete_note(self, project_id: str, note_id: str) -> None:
        self.get_note(project_id, note_id)  # ownership check
        self._notes.delete(note_id)
        try:
            self._vectors.delete(note_id)
        except Exception:
            logger.warning("knowledge_vector_delete_failed", extra={"note_id": note_id})

    def search(
        self,
        project_id: str,
        q: str,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[KnowledgeNote]:
        self._require_project(project_id)
        try:
            return _run_coro(self.search_async(project_id, q, limit=limit))
        except RuntimeError:
            return self._keyword_search(project_id, q, limit=limit)

    async def search_async(
        self,
        project_id: str,
        q: str,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[KnowledgeNote]:
        self._require_project(project_id)
        return await self._hybrid_search(project_id, q, limit=limit)

    def retrieve_for_prompt(
        self,
        project_id: str,
        query: str,
        *,
        top_k: int = DEFAULT_INJECT_TOP_K,
    ) -> list[KnowledgeNote]:
        """Best-effort sync retrieval; prefers keyword if async nest fails."""
        try:
            if not self._projects.get_project(project_id):
                return []
            try:
                return _run_coro(
                    self.retrieve_for_prompt_async(project_id, query, top_k=top_k)
                )
            except RuntimeError:
                return self._keyword_search(project_id, query, limit=top_k)
        except Exception:
            return []

    async def retrieve_for_prompt_async(
        self,
        project_id: str,
        query: str,
        *,
        top_k: int = DEFAULT_INJECT_TOP_K,
    ) -> list[KnowledgeNote]:
        try:
            if not self._projects.get_project(project_id):
                return []
            return await self._hybrid_search(project_id, query, limit=top_k)
        except Exception:
            return []

    def _keyword_search(
        self,
        project_id: str,
        q: str,
        *,
        limit: int,
    ) -> list[KnowledgeNote]:
        return self._notes.search(project_id, q, limit=limit)

    async def _hybrid_search(
        self,
        project_id: str,
        q: str,
        *,
        limit: int,
    ) -> list[KnowledgeNote]:
        notes = self._notes.list_by_project(project_id)
        if not notes:
            return []
        kw_scores = {n.id: score_note(n, q) for n in notes}
        kw_scores = {k: v for k, v in kw_scores.items() if v > 0}
        entries = self._vectors.list_for_project(project_id)
        vec_scores = await vector_scores_for_query(q, entries, client=self._embed)
        if not vec_scores:
            # keyword-only fallback
            return self._keyword_search(project_id, q, limit=limit)
        fused = fuse_scores(kw_scores, vec_scores)
        # Include vector-only hits even if keyword miss (synonym path)
        ranked = rank_by_fused(
            notes,
            id_fn=lambda n: n.id,
            fused=fused,
            updated_at_fn=lambda n: n.updated_at,
            limit=limit,
            min_score=0.0,
        )
        if ranked:
            return ranked
        return self._keyword_search(project_id, q, limit=limit)

    def _schedule_embed(self, note: KnowledgeNote) -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(self._embed_note(note))
            except Exception as exc:
                logger.warning(
                    "knowledge_embed_sync_failed",
                    extra={"note_id": note.id, "error": str(exc)},
                )
            return
        # Fire-and-forget when already in an event loop
        asyncio.create_task(self._embed_note_safe(note))

    async def _embed_note_safe(self, note: KnowledgeNote) -> None:
        try:
            await self._embed_note(note)
        except Exception as exc:
            logger.warning(
                "knowledge_embed_failed",
                extra={"note_id": note.id, "error": str(exc)},
            )

    async def _embed_note(self, note: KnowledgeNote) -> None:
        text = f"{note.title}\n{note.body}\n" + " ".join(note.tags or [])
        vec = await self._embed.embed(text)
        if not vec:
            return
        self._vectors.upsert(
            note.id,
            vec,
            model=self._embed.model,
            project_id=note.project_id,
        )

    @staticmethod
    def prompt_block(notes: list[KnowledgeNote] | None) -> str:
        return format_knowledge_prompt_block(notes)

    @staticmethod
    def optional_blob(notes: list[KnowledgeNote] | None) -> dict[str, Any] | None:
        return notes_to_optional_dict(notes)
