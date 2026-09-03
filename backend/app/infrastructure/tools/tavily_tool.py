"""Tavily Search API tool — real web search via Tavily."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config.settings import settings
from app.infrastructure.trace import trace_collector, TraceStatus

_TAVILY_API = "https://api.tavily.com/search"
_HTTP_TIMEOUT = 30.0


@dataclass
class TavilyResult:
    """Standardized Tavily search result."""
    items: list[dict] = field(default_factory=list)
    status: str = "success"
    total_found: int = 0
    error: str | None = None


async def tavily_search(
    query: str,
    max_results: int = 10,
    search_depth: str = "advanced",
    include_raw_content: bool = True,
    start_date: str | None = None,
    end_date: str | None = None,
    time_range: str | None = None,
) -> TavilyResult:
    """Execute a search via Tavily API.

    Args:
        query: Search query string
        max_results: Max 20
        search_depth: "basic" or "advanced"
        include_raw_content: Whether to include full page content
        start_date: Optional YYYY-MM-DD lower bound (Tavily start_date)
        end_date: Optional YYYY-MM-DD upper bound
        time_range: Optional day|week|month|year (coarser; prefer start_date for multi-year)

    Returns:
        TavilyResult with standardized structure:
          items[].title, .url, .content, .raw_content, .score, .published_date
    """
    api_key = settings.tavily_api_key
    if not api_key:
        return TavilyResult(
            items=[],
            status="no_api_key",
            total_found=0,
            error="TAVILY_API_KEY 未配置，请在 .env 中设置 TAVILY_API_KEY=xxx",
        )

    payload: dict[str, Any] = {
        "api_key": api_key,
        "query": query,
        "max_results": min(max_results, 20),
        "search_depth": search_depth,
        "include_raw_content": include_raw_content,
        "include_images": False,
        "include_answer": False,
    }
    if start_date:
        payload["start_date"] = str(start_date)[:10]
    if end_date:
        payload["end_date"] = str(end_date)[:10]
    if time_range and not start_date:
        payload["time_range"] = str(time_range)

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
            resp = await client.post(_TAVILY_API, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return TavilyResult(
            items=[],
            status="api_error",
            total_found=0,
            error=f"Tavily API error ({exc.response.status_code}): {exc.response.text[:200]}",
        )
    except httpx.RequestError as exc:
        return TavilyResult(
            items=[],
            status="network_error",
            total_found=0,
            error=f"Tavily 网络错误: {exc}",
        )

    results = data.get("results", [])
    items = []
    for r in results:
        items.append({
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": r.get("content", ""),
            "raw_content": r.get("raw_content", ""),
            "score": r.get("score", 0.0),
            "published_date": r.get("published_date", ""),
        })

    return TavilyResult(
        items=items,
        status="success",
        total_found=len(items),
    )
