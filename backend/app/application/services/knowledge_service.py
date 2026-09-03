"""Knowledge Notes application service (CRUD + search)."""

from __future__ import annotations

from typing import Any

from app.application.exceptions import KnowledgeNoteNotFoundError, ProjectNotFoundError
from app.domain.entities.copilot_common import utc_now
from app.domain.entities.knowledge_note import (
    DEFAULT_INJECT_TOP_K,
    DEFAULT_SEARCH_LIMIT,
    MAX_NOTES_PER_PROJECT,
    KnowledgeNote,
    format_knowledge_prompt_block,
    notes_to_optional_dict,
)
from app.infrastructure.persistence.copilot.knowledge_notes_store import KnowledgeNotesStore
from app.infrastructure.persistence.copilot.stores import ProjectStore, new_id


class KnowledgeService:
    def __init__(
        self,
        notes_store: KnowledgeNotesStore | None = None,
        project_store: ProjectStore | None = None,
    ) -> None:
        self._notes = notes_store or KnowledgeNotesStore()
        self._projects = project_store or ProjectStore()

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
        return self._notes.create(note)

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
        return self._notes.update(note)

    def delete_note(self, project_id: str, note_id: str) -> None:
        self.get_note(project_id, note_id)  # ownership check
        self._notes.delete(note_id)

    def search(
        self,
        project_id: str,
        q: str,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[KnowledgeNote]:
        self._require_project(project_id)
        return self._notes.search(project_id, q, limit=limit)

    def retrieve_for_prompt(
        self,
        project_id: str,
        query: str,
        *,
        top_k: int = DEFAULT_INJECT_TOP_K,
    ) -> list[KnowledgeNote]:
        """Best-effort retrieval for injection; empty on missing project / errors."""
        try:
            if not self._projects.get_project(project_id):
                return []
            return self._notes.search(project_id, query, limit=top_k)
        except Exception:
            return []

    @staticmethod
    def prompt_block(notes: list[KnowledgeNote] | None) -> str:
        return format_knowledge_prompt_block(notes)

    @staticmethod
    def optional_blob(notes: list[KnowledgeNote] | None) -> dict[str, Any] | None:
        return notes_to_optional_dict(notes)
