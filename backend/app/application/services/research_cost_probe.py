"""Minimal research-path cost counters for Evidence Reuse Step 3 benchmarks.

Test/benchmark only — not a production telemetry platform.
Wraps SourceRouter search entrypoints and llm_client.generate while active.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from typing import Any, Iterator


@dataclass
class ResearchCostSnapshot:
    task: str = ""
    reuse_mode: str = "full_research"  # zero_search | gap_search | full_research
    search_calls: int = 0
    llm_calls: int = 0
    llm_router_calls: int = 0
    llm_extraction_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    token_usage_unavailable: bool = False
    historical_evidence_count: int = 0
    reused_evidence_count: int = 0
    new_evidence_count: int = 0
    evidence_count: int = 0
    evidence_urls: list[str] = field(default_factory=list)
    evidence_ids: list[str] = field(default_factory=list)
    evidence_categories: list[str] = field(default_factory=list)
    route_dimensions: list[str] = field(default_factory=list)
    gap_keywords: list[str] = field(default_factory=list)
    pollution_flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ResearchCostProbe:
    """Collects Search / Research-LLM call counts during a scoped run."""

    def __init__(self) -> None:
        self.search_calls = 0
        self.llm_calls = 0
        self.llm_router_calls = 0
        self.llm_extraction_calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self._seen_token = False
        self._active_llm_phase: str | None = None

    def mark_llm_phase(self, phase: str | None) -> None:
        self._active_llm_phase = phase

    def record_search(self) -> None:
        self.search_calls += 1

    def record_llm(self, *, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
        self.llm_calls += 1
        if self._active_llm_phase == "router":
            self.llm_router_calls += 1
        elif self._active_llm_phase == "extraction":
            self.llm_extraction_calls += 1
        if prompt_tokens or completion_tokens:
            self._seen_token = True
            self.prompt_tokens += int(prompt_tokens or 0)
            self.completion_tokens += int(completion_tokens or 0)

    def snapshot(self, **extra: Any) -> ResearchCostSnapshot:
        total = self.prompt_tokens + self.completion_tokens
        return ResearchCostSnapshot(
            search_calls=self.search_calls,
            llm_calls=self.llm_calls,
            llm_router_calls=self.llm_router_calls,
            llm_extraction_calls=self.llm_extraction_calls,
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=total,
            token_usage_unavailable=not self._seen_token,
            **extra,
        )


@contextmanager
def install_research_cost_probe(probe: ResearchCostProbe | None = None) -> Iterator[ResearchCostProbe]:
    """Patch SourceRouter + llm_client for the duration of the with-block."""
    from app.infrastructure.llm import client as llm_mod
    from app.infrastructure.tools import source_router as sr_mod
    from app.infrastructure.tools import llm_router as lr_mod

    probe = probe or ResearchCostProbe()
    router = sr_mod.source_router
    llm = llm_mod.llm_client

    orig_execute = router.execute_plan
    orig_search_many = router.search_many
    orig_generate = llm.generate
    orig_route = lr_mod.llm_router.route

    async def _execute_plan(*args: Any, **kwargs: Any):
        probe.record_search()
        return await orig_execute(*args, **kwargs)

    async def _search_many(*args: Any, **kwargs: Any):
        probe.record_search()
        return await orig_search_many(*args, **kwargs)

    async def _generate(*args: Any, **kwargs: Any):
        result = await orig_generate(*args, **kwargs)
        probe.record_llm(
            prompt_tokens=int(getattr(result, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(result, "completion_tokens", 0) or 0),
        )
        return result

    async def _route(*args: Any, **kwargs: Any):
        probe.mark_llm_phase("router")
        try:
            return await orig_route(*args, **kwargs)
        finally:
            probe.mark_llm_phase(None)

    router.execute_plan = _execute_plan  # type: ignore[method-assign]
    router.search_many = _search_many  # type: ignore[method-assign]
    llm.generate = _generate  # type: ignore[method-assign]
    lr_mod.llm_router.route = _route  # type: ignore[method-assign]

    # Extraction uses llm_client.generate — tag phase around ResearchAgent extract
    from app.infrastructure.agents import research_agent as ra_mod

    orig_extract = ra_mod.ResearchAgent._extract_evidence_from_sources

    async def _extract(self: Any, *args: Any, **kwargs: Any):
        probe.mark_llm_phase("extraction")
        try:
            return await orig_extract(self, *args, **kwargs)
        finally:
            probe.mark_llm_phase(None)

    ra_mod.ResearchAgent._extract_evidence_from_sources = _extract  # type: ignore[method-assign]

    try:
        yield probe
    finally:
        router.execute_plan = orig_execute  # type: ignore[method-assign]
        router.search_many = orig_search_many  # type: ignore[method-assign]
        llm.generate = orig_generate  # type: ignore[method-assign]
        lr_mod.llm_router.route = orig_route  # type: ignore[method-assign]
        ra_mod.ResearchAgent._extract_evidence_from_sources = orig_extract  # type: ignore[method-assign]
