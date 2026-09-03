"""Shared evidence compression for compact Compare/Strategy prompts (Step 40)."""

from __future__ import annotations

from typing import Any


_TEMPORAL_PRIORITY: dict[str, float] = {
    "recent": 0.0,
    "aging": 1.0,
    "mixed": 1.5,
    "unknown": 2.0,
    "stale": 3.0,
    "historical": 4.0,
}
_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2, "estimated": 3}

COMPACT_EVIDENCE_CAP = 8
COMPACT_SNIPPET_CHARS = 250


def _dget(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _temporal_level(item: Any) -> str:
    qs = _dget(item, "quality_score", None) or {}
    if isinstance(qs, dict):
        return qs.get("temporal_level", "") or ""
    return getattr(qs, "temporal_level", "") or ""


def evidence_sort_key(item: Any) -> tuple[float, int]:
    level = _temporal_level(item) or "unknown"
    confidence = _dget(item, "confidence", "estimated")
    return (
        _TEMPORAL_PRIORITY.get(level, 2.0),
        _CONFIDENCE_RANK.get(str(confidence), 3),
    )


def compress_evidence_items(
    items: list[Any] | None,
    *,
    cap: int = COMPACT_EVIDENCE_CAP,
    snippet_chars: int = COMPACT_SNIPPET_CHARS,
) -> list[dict[str, Any]]:
    """Sort by freshness/confidence, truncate count + snippet for LLM input."""
    raw = list(items or [])
    selected = sorted(raw, key=evidence_sort_key)[: max(1, int(cap))]
    out: list[dict[str, Any]] = []
    for e in selected:
        content = str(_dget(e, "content", "") or "")
        out.append({
            "id": _dget(e, "id", "") or "",
            "title": str(_dget(e, "title", "") or "")[:120],
            "source": _dget(e, "source", "") or "",
            "date": _dget(e, "date", "") or "",
            "date_semantic": (
                (_dget(e, "raw_data", None) or {}).get("date_semantic")
                if isinstance(_dget(e, "raw_data", None), dict)
                else ""
            ) or "unknown",
            "dimension": _dget(e, "category", "") or "",
            "summary": content[:snippet_chars],
            "confidence": _dget(e, "confidence", "estimated") or "estimated",
            "temporal_level": _temporal_level(e) or "unknown",
        })
    return out
