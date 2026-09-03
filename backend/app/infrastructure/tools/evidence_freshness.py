"""Evidence age window filter + lightweight page-meta date enrichment (Step 42)."""

from __future__ import annotations

import asyncio
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from app.infrastructure.tools.evidence_date import (
    _SEMANTIC_PUBLISH,
    compute_temporal_confidence,
    normalize_existing_date,
)

_DATE_SOURCE_PAGE_META = "page_meta"
_MAX_BODY_BYTES = 96 * 1024

_META_PATTERNS = [
    re.compile(
        r'<meta[^>]+(?:property|name)=["\'](?:article:published_time|og:published_time|'
        r'publish(?:ed)?_?date|pubdate|date|DC\.date\.issued)["\'][^>]+'
        r'content=["\']([^"\']+)["\']',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+'
        r'(?:property|name)=["\'](?:article:published_time|og:published_time|'
        r'publish(?:ed)?_?date|pubdate|date)["\']',
        re.I,
    ),
    re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I),
    re.compile(
        r'["\']datePublished["\']\s*:\s*["\']([^"\']+)["\']',
        re.I,
    ),
]

_SKIP_PATH_HINTS = re.compile(
    r"(?:^|/)(?:abouts?|about-us|contact|login|signup|home)/?$",
    re.I,
)


def evidence_cutoff_date(max_age_months: int = 48, *, today: date | None = None) -> date:
    """Approximate calendar cutoff: today minus max_age_months."""
    today = today or date.today()
    months = max(1, int(max_age_months or 48))
    year = today.year
    month = today.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(today.day, 28)
    try:
        return date(year, month, day)
    except ValueError:
        return date(year, month, 1)


def cutoff_iso(max_age_months: int = 48, *, today: date | None = None) -> str:
    return evidence_cutoff_date(max_age_months, today=today).isoformat()


def freshness_query_hint(max_age_months: int = 48, *, today: date | None = None) -> str:
    cutoff = evidence_cutoff_date(max_age_months, today=today)
    return f"优先{cutoff.year}年至今的公开信息"


def _dget(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _parse_item_date(item: Any) -> date | None:
    raw = str(_dget(item, "date", "") or "").strip()
    if not raw:
        return None
    normalized = normalize_existing_date(raw) or raw[:10]
    try:
        return datetime.strptime(normalized[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _set_item_date_meta(
    item: Any,
    *,
    date_value: str,
    date_source: str,
    date_semantic: str,
) -> None:
    if hasattr(item, "date"):
        item.date = date_value
    elif isinstance(item, dict):
        item["date"] = date_value
    raw = _dget(item, "raw_data", None)
    if not isinstance(raw, dict):
        raw = {}
    else:
        raw = dict(raw)
    conf = compute_temporal_confidence(
        date_source=date_source,
        date_semantic=date_semantic,
        has_date=True,
    )
    # page_meta → at least medium
    if date_source == _DATE_SOURCE_PAGE_META and conf == "low":
        conf = "medium"
    raw["date_source"] = date_source
    raw["date_semantic"] = date_semantic
    raw["temporal_confidence"] = conf
    if hasattr(item, "raw_data"):
        item.raw_data = raw
    elif isinstance(item, dict):
        item["raw_data"] = raw
    qs = _dget(item, "quality_score", None)
    if isinstance(qs, dict) or qs is None:
        qs = dict(qs or {})
        qs["temporal_confidence"] = conf
        if hasattr(item, "quality_score"):
            item.quality_score = qs
        elif isinstance(item, dict):
            item["quality_score"] = qs


def apply_evidence_age_window(
    items: list[Any] | None,
    *,
    max_age_months: int = 48,
    max_undated_evidence_items: int = 5,
    today: date | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    """Filter main evidence list to in-window dated + capped undated."""
    cutoff = evidence_cutoff_date(max_age_months, today=today)
    items = list(items or [])
    kept_dated: list[Any] = []
    undated: list[Any] = []
    expired: list[Any] = []

    for item in items:
        d = _parse_item_date(item)
        if d is None:
            undated.append(item)
            continue
        if d < cutoff:
            expired.append(item)
            continue
        # in-window dated (incl. event_date) kept for main analysis
        kept_dated.append(item)

    undated_cap = max(0, int(max_undated_evidence_items))
    undated_kept = undated[:undated_cap]
    undated_dropped = undated[undated_cap:]

    main = kept_dated + undated_kept
    # Stable re-id left to caller
    meta = {
        "evidence_cutoff_date": cutoff.isoformat(),
        "filtered_expired_count": len(expired),
        "undated_kept_count": len(undated_kept),
        "undated_dropped_count": len(undated_dropped),
        "in_window_dated_count": len(kept_dated),
    }
    return main, meta


def looks_like_article_url(url: str) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    try:
        path = urlparse(url).path or "/"
    except Exception:
        return False
    if _SKIP_PATH_HINTS.search(path.rstrip("/") or "/"):
        return False
    # Prefer paths with article-ish signals
    if re.search(r"\d{4}|article|news|information|post|blog|doc-", path, re.I):
        return True
    # Still allow deep paths
    return path.count("/") >= 2 and len(path) > 8


def extract_published_date_from_html(html: str) -> str | None:
    if not html:
        return None
    for pat in _META_PATTERNS:
        m = pat.search(html)
        if not m:
            continue
        parsed = normalize_existing_date(m.group(1)) or None
        if parsed:
            return parsed
        # ISO prefix
        raw = (m.group(1) or "").strip()
        if len(raw) >= 10:
            parsed = normalize_existing_date(raw[:10])
            if parsed:
                return parsed
    return None


async def _fetch_html_prefix(url: str, timeout_s: float) -> str:
    limits = httpx.Limits(max_keepalive_connections=2, max_connections=4)
    async with httpx.AsyncClient(
        timeout=timeout_s,
        follow_redirects=True,
        limits=limits,
        headers={"User-Agent": "product-tools-date-enrich/1.0"},
    ) as client:
        async with client.stream("GET", url) as resp:
            if resp.status_code >= 400:
                return ""
            ctype = (resp.headers.get("content-type") or "").lower()
            if "html" not in ctype and "text" not in ctype and ctype:
                return ""
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= _MAX_BODY_BYTES:
                    break
            return b"".join(chunks).decode("utf-8", errors="ignore")


async def enrich_missing_dates_from_page_meta(
    items: list[Any] | None,
    *,
    enabled: bool = True,
    max_urls: int = 8,
    timeout_s: float = 2.5,
    concurrency: int = 3,
) -> dict[str, Any]:
    """Fill empty dates from HTML meta tags (best-effort, never raises)."""
    stats = {"attempted": 0, "succeeded": 0, "failed": 0, "skipped": 0}
    if not enabled or not items:
        return stats

    candidates: list[Any] = []
    for item in items:
        if str(_dget(item, "date", "") or "").strip():
            continue
        url = str(_dget(item, "url", "") or "")
        if not looks_like_article_url(url):
            stats["skipped"] += 1
            continue
        candidates.append(item)
        if len(candidates) >= max(0, int(max_urls)):
            break

    if not candidates:
        return stats

    sem = asyncio.Semaphore(max(1, int(concurrency)))

    async def _one(item: Any) -> None:
        url = str(_dget(item, "url", "") or "")
        stats["attempted"] += 1
        try:
            async with sem:
                html = await _fetch_html_prefix(url, float(timeout_s))
            parsed = extract_published_date_from_html(html)
            if parsed:
                _set_item_date_meta(
                    item,
                    date_value=parsed,
                    date_source=_DATE_SOURCE_PAGE_META,
                    date_semantic=_SEMANTIC_PUBLISH,
                )
                stats["succeeded"] += 1
            else:
                stats["failed"] += 1
        except Exception:
            stats["failed"] += 1

    await asyncio.gather(*[_one(it) for it in candidates])
    return stats
