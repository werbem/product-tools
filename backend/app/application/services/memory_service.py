"""Project Memory application service (read/patch for API)."""

from __future__ import annotations

from typing import Any

from app.application.exceptions import ProjectNotFoundError
from app.domain.entities.copilot_common import utc_now
from app.domain.entities.project_memory import (
    MemoryFinding,
    ProjectMemory,
    ProjectMemoryEntities,
)
from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore
from app.infrastructure.persistence.copilot.stores import ProjectStore


class MemoryService:
    def __init__(
        self,
        memory_store: ProjectMemoryStore | None = None,
        project_store: ProjectStore | None = None,
    ) -> None:
        self._memory_store = memory_store or ProjectMemoryStore()
        self._project_store = project_store or ProjectStore()

    def get_memory(self, project_id: str) -> ProjectMemory:
        if not self._project_store.get_project(project_id):
            raise ProjectNotFoundError(project_id)
        return self._memory_store.get_or_empty(project_id)

    def patch_memory(self, project_id: str, patch: dict[str, Any]) -> ProjectMemory:
        if not self._project_store.get_project(project_id):
            raise ProjectNotFoundError(project_id)
        memory = self._memory_store.get_or_empty(project_id)

        if "entities" in patch and isinstance(patch["entities"], dict):
            incoming = ProjectMemoryEntities.from_dict(patch["entities"])
            # PATCH replaces provided entity fields (explicit null clears)
            raw = patch["entities"]
            memory.entities = ProjectMemoryEntities(
                our_company=incoming.our_company if "our_company" in raw else memory.entities.our_company,
                competitors=(
                    incoming.competitors if "competitors" in raw else memory.entities.competitors
                ),
                product=incoming.product if "product" in raw else memory.entities.product,
                industry=incoming.industry if "industry" in raw else memory.entities.industry,
            )

        if "open_questions" in patch and isinstance(patch["open_questions"], list):
            memory.open_questions = [str(q).strip() for q in patch["open_questions"] if str(q).strip()]

        if "key_findings" in patch and isinstance(patch["key_findings"], list):
            findings: list[MemoryFinding] = []
            for item in patch["key_findings"]:
                if isinstance(item, str) and item.strip():
                    findings.append(
                        MemoryFinding(text=item.strip(), source_type="manual", updated_at=utc_now()),
                    )
                elif isinstance(item, dict) and item.get("text"):
                    findings.append(MemoryFinding.from_dict({**item, "source_type": item.get("source_type") or "manual"}))
            memory.key_findings = findings

        memory.updated_at = utc_now()
        return self._memory_store.upsert(memory)
