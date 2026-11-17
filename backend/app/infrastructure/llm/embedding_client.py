"""OpenAI-compatible embeddings with graceful keyword-only fallback.

Phase 4b: short timeout so Intent/Deep share the same worker safely.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Sequence

from openai import AsyncOpenAI

from app.config.settings import settings

logger = logging.getLogger(__name__)


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def normalize_scores(scores: dict[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    mx = max(scores.values())
    if mx <= 0:
        return {k: 0.0 for k in scores}
    return {k: float(v) / mx for k, v in scores.items()}


class EmbeddingClient:
    """Thin wrapper; returns None / empty on any failure (caller falls back)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
    ) -> None:
        self._api_key = (api_key if api_key is not None else settings.effective_api_key) or ""
        self._base_url = (
            base_url if base_url is not None else (settings.openai_base_url or "")
        ).strip()
        self._model = (
            model if model is not None else (settings.embedding_model or "text-embedding-3-small")
        ).strip()
        raw_t = timeout_s if timeout_s is not None else float(settings.embedding_timeout_s or 8.0)
        self._timeout_s = max(2.0, min(30.0, float(raw_t)))

    @property
    def model(self) -> str:
        return self._model

    @property
    def available(self) -> bool:
        return bool(self._api_key) and settings.llm_provider.value != "mock"

    async def embed(self, text: str) -> list[float] | None:
        texts = await self.embed_many([text])
        if not texts:
            return None
        return texts[0]

    async def embed_many(self, texts: list[str]) -> list[list[float]] | None:
        cleaned = [(t or "").strip() for t in texts]
        if not any(cleaned):
            return None
        if not self.available:
            return None
        try:
            return await asyncio.wait_for(
                self._call_openai(cleaned),
                timeout=self._timeout_s,
            )
        except Exception as exc:
            logger.warning(
                "embedding_failed",
                extra={"error": str(exc), "model": self._model, "n": len(cleaned)},
            )
            return None

    async def _call_openai(self, texts: list[str]) -> list[list[float]]:
        kwargs: dict = {"api_key": self._api_key, "timeout": self._timeout_s}
        if self._base_url:
            kwargs["base_url"] = self._base_url
        client = AsyncOpenAI(**kwargs)
        # Truncate each input to keep payload small
        inputs = [t[:8000] if t else " " for t in texts]
        resp = await client.embeddings.create(model=self._model, input=inputs)
        by_idx = {item.index: list(item.embedding) for item in resp.data}
        return [by_idx[i] for i in range(len(inputs))]


embedding_client = EmbeddingClient()
