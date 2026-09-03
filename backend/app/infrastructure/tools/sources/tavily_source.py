"""Tavily Web Search Source — implements ResearchSource interface.

Wraps the existing tavily_tool.py with the unified Source interface.
Provides:
  - real web search via Tavily API
  - standardized EvidenceItem output
  - no mock fallback (if no API key, returns SourceResult with status='no_api_key')
  - trace integration for debugging
"""

from __future__ import annotations

import time
from typing import Optional

from app.infrastructure.tools.research_source import (
    EvidenceItem,
    ResearchSource,
    SourceResult,
    SourceType,
)
from app.infrastructure.tools.tavily_tool import TavilyResult, tavily_search
from app.infrastructure.trace import trace_collector, TraceStatus


class TavilySource(ResearchSource):
    """Real web search via Tavily API.

    Queries:        Tavily Search API (https://api.tavily.com)
    Auth:           TAVILY_API_KEY env var
    Output format:  unified EvidenceItem
    """

    DEFAULT_MAX_RESULTS = 5
    DEFAULT_SEARCH_DEPTH = "basic"

    @property
    def name(self) -> str:
        return "Tavily Web Search"

    @property
    def source_type(self) -> str:
        return SourceType.WEB

    async def search(
        self,
        query: str,
        context: Optional[dict] = None,
    ) -> SourceResult:
        """Execute a Tavily web search.

        Args:
            query: Search query string
            context: Optional dict with task metadata

        Returns:
            SourceResult with EvidenceItem list
        """
        task_id = (context or {}).get("task_id", "unknown")
        start = time.time()
        ctx = context or {}
        max_results = int(ctx.get("max_results_per_source") or self.DEFAULT_MAX_RESULTS)
        max_results = max(1, min(max_results, 20))
        start_date = str(ctx.get("evidence_start_date") or "").strip() or None
        hint = str(ctx.get("freshness_query_hint") or "").strip()
        search_query = query
        if hint and hint not in query:
            search_query = f"{query} {hint}".strip()

        # --- Trace: search start ---
        trace = trace_collector.start_trace(
            task_id=task_id,
            stage="search_tool",
            agent_name="research",
            input_summary=f"Tavily: {search_query[:100]}",
            metadata={
                "source": "tavily",
                "query": search_query,
                "start_date": start_date or "",
            },
        )
        # ---

        # Execute Tavily API call (reuse existing function)
        tavily_result: TavilyResult = await tavily_search(
            query=search_query,
            max_results=max_results,
            search_depth=self.DEFAULT_SEARCH_DEPTH,
            # Raw page HTML is huge and often stalls LLM evidence extraction.
            include_raw_content=False,
            start_date=start_date,
        )

        duration_ms = int((time.time() - start) * 1000)

        # Handle errors
        if tavily_result.error:
            error_str = str(tavily_result.error)
            # Map TavilyResult status → SourceResult status
            _status_map = {"network_error": "error", "api_error": "error", "no_api_key": "no_api_key"}
            trace_collector.end_trace(
                trace,
                success=False,
                output_summary=f"Tavily error: {error_str[:200]}",
                error=error_str,
                metadata={"duration_ms": duration_ms, "query": query},
            )
            return SourceResult(
                items=[],
                source_type=SourceType.WEB,
                source_name=self.name,
                status=_status_map.get(tavily_result.status, "error"),
                error=error_str,
                total_found=0,
                duration_ms=duration_ms,
            )

        # Convert Tavily items to unified EvidenceItem
        evidence_items: list[EvidenceItem] = []
        for item in tavily_result.items:
            evidence = EvidenceItem(
                source_type=SourceType.WEB,
                source_name=self.name,
                title=item.get("title", ""),
                url=item.get("url", ""),
                content=item.get("content", "") or item.get("raw_content", "") or "",
                published_date=item.get("published_date", ""),
                author="",
                metrics={"score": item.get("score", 0.0)},
                dimension="",     # filled by LLM later
                confidence="medium",  # reassessed by LLM
            )
            evidence_items.append(evidence)

        # --- Trace: search end ---
        trace_collector.end_trace(
            trace,
            success=True,
            output_summary=f"Tavily returned {len(evidence_items)} results for '{query[:100]}'",
            metadata={
                "duration_ms": duration_ms,
                "query": query,
                "result_count": len(evidence_items),
            },
        )
        # ---

        if not evidence_items:
            return SourceResult(
                items=[],
                source_type=SourceType.WEB,
                source_name=self.name,
                status="no_data",
                error=None,
                total_found=0,
                duration_ms=duration_ms,
            )

        return SourceResult(
            items=evidence_items,
            source_type=SourceType.WEB,
            source_name=self.name,
            status="success",
            total_found=len(evidence_items),
            duration_ms=duration_ms,
        )


# ── Singleton ──
tavily_source = TavilySource()
