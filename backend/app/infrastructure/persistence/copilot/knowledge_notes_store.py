"""Knowledge notes JSON store (Phase 3 V3.2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.entities.knowledge_note import (
    DEFAULT_SEARCH_LIMIT,
    KnowledgeNote,
    score_note,
)
from app.infrastructure.persistence.copilot.json_file_store import JsonFileStore
from app.infrastructure.persistence.copilot.stores import DATA_DIR


class KnowledgeNotesStore:
    """Flat map: { note_id: KnowledgeNote dict }."""

    def __init__(self, base_dir: Path | None = None) -> None:
        base = base_dir or DATA_DIR
        self._store = JsonFileStore(base / "knowledge_notes.json")

    def create(self, note: KnowledgeNote) -> KnowledgeNote:
        note.enforce_limits()

        def _create(data: dict[str, Any]) -> KnowledgeNote:
            data[note.id] = note.to_dict()
            return note

        return self._store.mutate(_create)

    def get(self, note_id: str) -> KnowledgeNote | None:
        raw = self._store.load().get(note_id)
        if not raw or not isinstance(raw, dict):
            return None
        try:
            return KnowledgeNote.from_dict(raw)
        except Exception:
            return None

    def list_by_project(self, project_id: str) -> list[KnowledgeNote]:
        notes: list[KnowledgeNote] = []
        for raw in self._store.load().values():
            if not isinstance(raw, dict):
                continue
            if str(raw.get("project_id") or "") != project_id:
                continue
            try:
                notes.append(KnowledgeNote.from_dict(raw))
            except Exception:
                continue
        notes.sort(key=lambda n: n.updated_at, reverse=True)
        return notes

    def update(self, note: KnowledgeNote) -> KnowledgeNote:
        note.enforce_limits()

        def _update(data: dict[str, Any]) -> KnowledgeNote:
            data[note.id] = note.to_dict()
            return note

        return self._store.mutate(_update)

    def delete(self, note_id: str) -> bool:
        found = {"ok": False}

        def _delete(data: dict[str, Any]) -> None:
            if note_id in data:
                data.pop(note_id, None)
                found["ok"] = True

        self._store.mutate(_delete)
        return found["ok"]

    def count_by_project(self, project_id: str) -> int:
        return len(self.list_by_project(project_id))

    def search(
        self,
        project_id: str,
        q: str,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[KnowledgeNote]:
        limit = max(1, min(int(limit or DEFAULT_SEARCH_LIMIT), 20))
        scored: list[tuple[float, KnowledgeNote]] = []
        for note in self.list_by_project(project_id):
            s = score_note(note, q)
            if s > 0:
                scored.append((s, note))
        scored.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [n for _, n in scored[:limit]]
