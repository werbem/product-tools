"""Index and retrieve ProjectMemory key_findings via embeddings (Phase 4b)."""

from __future__ import annotations

import hashlib
import logging
from typing import Sequence

from app.application.services.hybrid_retrieval import (
    fuse_scores,
    rank_by_fused,
    vector_scores_for_query,
)
from app.domain.entities.project_memory import MemoryFinding, ProjectMemory
from app.infrastructure.llm.embedding_client import EmbeddingClient
from app.infrastructure.persistence.copilot.vector_store import VectorJsonStore

logger = logging.getLogger(__name__)


def finding_vector_id(project_id: str, text: str) -> str:
    digest = hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]
    return f"{project_id}:kf:{digest}"


class MemoryFindingsIndex:
    def __init__(
        self,
        vector_store: VectorJsonStore | None = None,
        embedding_client: EmbeddingClient | None = None,
    ) -> None:
        self._vectors = vector_store or VectorJsonStore("project_memory_vectors.json")
        self._embed = embedding_client or EmbeddingClient()

    async def reindex(self, project_id: str, findings: Sequence[MemoryFinding]) -> None:
        """Replace all finding vectors for a project (best-effort)."""
        try:
            for kid in list(self._vectors.list_for_project(project_id)):
                self._vectors.delete(kid)
            for finding in findings:
                text = (finding.text or "").strip()
                if not text:
                    continue
                vec = await self._embed.embed(text)
                if not vec:
                    continue
                self._vectors.upsert(
                    finding_vector_id(project_id, text),
                    vec,
                    model=self._embed.model,
                    project_id=project_id,
                    meta={"text": text[:200]},
                )
        except Exception as exc:
            logger.warning(
                "memory_findings_reindex_failed",
                extra={"project_id": project_id, "error": str(exc)},
            )

    async def rank_findings(
        self,
        memory: ProjectMemory,
        query: str,
        *,
        limit: int = 5,
    ) -> list[MemoryFinding]:
        findings = list(memory.key_findings or [])
        if not findings or not (query or "").strip():
            return findings[:limit]

        # Keyword overlap score (substring)
        q = query.strip().lower()
        kw: dict[str, float] = {}
        by_id: dict[str, MemoryFinding] = {}
        for f in findings:
            fid = finding_vector_id(memory.project_id, f.text)
            by_id[fid] = f
            text_l = (f.text or "").lower()
            score = 0.0
            if q in text_l:
                score += 5.0
            for token in q.replace("，", " ").replace(",", " ").split():
                if len(token) >= 2 and token in text_l:
                    score += 1.0
            if score > 0:
                kw[fid] = score

        entries = self._vectors.list_for_project(memory.project_id)
        vec = await vector_scores_for_query(query, entries, client=self._embed)
        if not vec and not kw:
            return findings[:limit]
        fused = fuse_scores(kw, vec) if vec else {k: v for k, v in kw.items()}
        ranked = rank_by_fused(
            list(by_id.values()),
            id_fn=lambda f: finding_vector_id(memory.project_id, f.text),
            fused=fused,
            updated_at_fn=lambda f: f.updated_at,
            limit=limit,
        )
        return ranked or findings[:limit]


memory_findings_index = MemoryFindingsIndex()
