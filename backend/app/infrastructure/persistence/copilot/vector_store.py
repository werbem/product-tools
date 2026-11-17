"""JSON vector stores for Knowledge Notes and Memory findings (Phase 4b)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.infrastructure.persistence.copilot.json_file_store import JsonFileStore
from app.infrastructure.persistence.copilot.stores import DATA_DIR


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class VectorJsonStore:
    """Flat map: { id: { vector, model, updated_at, project_id? } }."""

    def __init__(self, filename: str, base_dir: Path | None = None) -> None:
        base = base_dir or DATA_DIR
        self._store = JsonFileStore(base / filename)

    def upsert(
        self,
        item_id: str,
        vector: list[float],
        *,
        model: str,
        project_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> None:
        def _mut(data: dict[str, Any]) -> None:
            row: dict[str, Any] = {
                "vector": list(vector),
                "model": model,
                "updated_at": _utc_iso(),
            }
            if project_id is not None:
                row["project_id"] = project_id
            if meta:
                row["meta"] = meta
            data[item_id] = row

        self._store.mutate(_mut)

    def get(self, item_id: str) -> dict[str, Any] | None:
        raw = self._store.load().get(item_id)
        return raw if isinstance(raw, dict) else None

    def delete(self, item_id: str) -> bool:
        found = {"ok": False}

        def _mut(data: dict[str, Any]) -> None:
            if item_id in data:
                data.pop(item_id, None)
                found["ok"] = True

        self._store.mutate(_mut)
        return found["ok"]

    def list_for_project(self, project_id: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for kid, raw in self._store.load().items():
            if not isinstance(raw, dict):
                continue
            if str(raw.get("project_id") or "") != project_id:
                continue
            out[str(kid)] = raw
        return out

    def all_entries(self) -> dict[str, dict[str, Any]]:
        data = self._store.load()
        return {str(k): v for k, v in data.items() if isinstance(v, dict)}
