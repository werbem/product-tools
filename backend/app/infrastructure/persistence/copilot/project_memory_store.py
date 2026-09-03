"""ProjectMemory JSON store (Phase 3 V3.1)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.entities.project_memory import ProjectMemory
from app.infrastructure.persistence.copilot.json_file_store import JsonFileStore
from app.infrastructure.persistence.copilot.stores import DATA_DIR


class ProjectMemoryStore:
    def __init__(self, base_dir: Path | None = None) -> None:
        base = base_dir or DATA_DIR
        self._store = JsonFileStore(base / "project_memory.json")

    def get(self, project_id: str) -> ProjectMemory | None:
        raw = self._store.load().get(project_id)
        if not raw or not isinstance(raw, dict):
            return None
        try:
            return ProjectMemory.from_dict(raw)
        except Exception:
            return None

    def upsert(self, memory: ProjectMemory) -> ProjectMemory:
        memory.enforce_limits()

        def _upsert(data: dict[str, Any]) -> ProjectMemory:
            data[memory.project_id] = memory.to_dict()
            return memory

        return self._store.mutate(_upsert)

    def delete(self, project_id: str) -> None:
        def _delete(data: dict[str, Any]) -> None:
            data.pop(project_id, None)

        self._store.mutate(_delete)

    def get_or_empty(self, project_id: str) -> ProjectMemory:
        return self.get(project_id) or ProjectMemory.empty(project_id)
