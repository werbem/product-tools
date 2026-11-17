"""Hybrid keyword + embedding retrieval helpers (Phase 4b)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Sequence, TypeVar

from app.infrastructure.llm.embedding_client import (
    EmbeddingClient,
    cosine_similarity,
    normalize_scores,
)

T = TypeVar("T")

KW_WEIGHT = 0.4
VEC_WEIGHT = 0.6


def fuse_scores(
    kw_scores: dict[str, float],
    vec_scores: dict[str, float],
    *,
    kw_weight: float = KW_WEIGHT,
    vec_weight: float = VEC_WEIGHT,
) -> dict[str, float]:
    """Weighted fusion of normalized keyword and vector scores."""
    ids = set(kw_scores) | set(vec_scores)
    kn = normalize_scores(kw_scores)
    vn = normalize_scores(vec_scores)
    return {
        i: kw_weight * kn.get(i, 0.0) + vec_weight * vn.get(i, 0.0)
        for i in ids
    }


def rank_by_fused(
    items: Sequence[T],
    *,
    id_fn: Callable[[T], str],
    fused: dict[str, float],
    updated_at_fn: Callable[[T], datetime] | None = None,
    limit: int,
    min_score: float = 0.0,
) -> list[T]:
    scored: list[tuple[float, datetime | None, T]] = []
    for item in items:
        iid = id_fn(item)
        s = float(fused.get(iid, 0.0))
        if s <= min_score and iid not in fused:
            continue
        if s <= 0:
            continue
        ts = updated_at_fn(item) if updated_at_fn else None
        scored.append((s, ts, item))
    scored.sort(
        key=lambda row: (row[0], row[1] or datetime.min),
        reverse=True,
    )
    return [row[2] for row in scored[: max(1, limit)]]


async def vector_scores_for_query(
    query: str,
    entries: dict[str, dict[str, Any]],
    *,
    client: EmbeddingClient | None = None,
) -> dict[str, float]:
    """Embed query and score against stored vectors; empty on failure."""
    client = client or EmbeddingClient()
    q_vec = await client.embed(query)
    if not q_vec:
        return {}
    out: dict[str, float] = {}
    for iid, row in entries.items():
        vec = row.get("vector")
        if not isinstance(vec, list) or not vec:
            continue
        try:
            out[iid] = cosine_similarity(q_vec, [float(x) for x in vec])
        except (TypeError, ValueError):
            continue
    return out
