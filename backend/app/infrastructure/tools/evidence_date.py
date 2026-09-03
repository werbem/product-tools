"""Deterministic evidence date enrichment (no LLM).

Step 37 + Step 41:
- Fill empty dates from published_date / URL / title / snippet
- Multi-date texts prefer the **most recent** valid YMD (not last occurrence)
- Timeline/abouts pages mark event_date semantics with low confidence
"""

from __future__ import annotations

import re
from calendar import monthrange
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import unquote

_MIN_YEAR = 1990

_DATE_SOURCE_UNCHANGED = "unchanged"
_DATE_SOURCE_PUBLISHED = "published_date"
_DATE_SOURCE_URL = "url"
_DATE_SOURCE_TITLE = "title"
_DATE_SOURCE_SNIPPET = "snippet"
_DATE_SOURCE_SNIPPET_RECENT = "snippet_recent"
_DATE_SOURCE_TIMELINE = "timeline_event_recent"
_DATE_SOURCE_PAGE_META = "page_meta"
_DATE_SOURCE_NONE = "none"

_SEMANTIC_PUBLISH = "publish_date"
_SEMANTIC_EVENT = "event_date"
_SEMANTIC_UNKNOWN = "unknown"

_TIMELINE_RE = re.compile(
    r"(?:^|/)(?:about|abouts)(?:/|\?|#|\s|$)|"
    r"大事记|发展历程|发展历史|历程|"
    r"memorabilia|timeline|(?:^|/)history(?:/|\?|#|\s|$)|company[-_]?history",
    re.IGNORECASE,
)

_PUBLISH_SOURCES = frozenset({_DATE_SOURCE_PUBLISHED, _DATE_SOURCE_PAGE_META})


def _max_year() -> int:
    return datetime.now().year + 1


def _today() -> date:
    return datetime.now().date()


def _is_valid_ymd(year: int, month: int, day: int) -> bool:
    if year < _MIN_YEAR or year > _max_year():
        return False
    if month < 1 or month > 12:
        return False
    last = monthrange(year, month)[1]
    return 1 <= day <= last


def _fmt(year: int, month: int, day: int) -> str | None:
    if not _is_valid_ymd(year, month, day):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_ymd(date_str: str) -> date | None:
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _collect_from_text(text: str) -> list[tuple[int, str, int]]:
    """Return list of (priority, YYYY-MM-DD, end_index).

    priority: lower is better (0 = dashed/chinese YMD, 1 = compact).
    """
    if not text:
        return []
    found: list[tuple[int, str, int]] = []

    for m in re.finditer(
        r"(?<!\d)(20\d{2}|19\d{2})([-/.])(\d{1,2})\2(\d{1,2})"
        r"(?:[T\s]\d{1,2}:\d{2}(?::\d{2})?(?:Z|[+-]\d{2}:?\d{2})?)?(?!\d)",
        text,
    ):
        y, mo, d = int(m.group(1)), int(m.group(3)), int(m.group(4))
        formatted = _fmt(y, mo, d)
        if formatted:
            found.append((0, formatted, m.end()))

    for m in re.finditer(r"(?<!\d)((?:19|20)\d{2})(\d{2})(\d{2})(?!\d)", text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        formatted = _fmt(y, mo, d)
        if formatted:
            found.append((1, formatted, m.end()))

    for m in re.finditer(r"(?<!\d)((?:19|20)\d{2})年(\d{1,2})月(\d{1,2})日", text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        formatted = _fmt(y, mo, d)
        if formatted:
            found.append((0, formatted, m.end()))

    return found


def pick_best_date(candidates: Iterable[tuple[int, str, int]]) -> str | None:
    """Prefer complete YMD, then the chronologically most recent (not last occurrence)."""
    items = list(candidates)
    if not items:
        return None
    today = _today()
    valid: list[tuple[int, str, date]] = []
    for pri, ds, _end in items:
        d = _parse_ymd(ds)
        if d is None:
            continue
        # Discard dates more than 1 day in the future
        if (d - today).days > 1:
            continue
        valid.append((pri, ds, d))
    if not valid:
        return None
    complete = [v for v in valid if v[0] == 0]
    pool = complete or valid
    best = max(pool, key=lambda x: x[2])
    return best[1]


def extract_date_from_text(text: str) -> str | None:
    return pick_best_date(_collect_from_text(text or ""))


def extract_date_from_url(url: str) -> str | None:
    if not url:
        return None
    return extract_date_from_text(unquote(url))


def is_timeline_context(
    *,
    url: str = "",
    title: str = "",
    content: str = "",
) -> bool:
    blob = " ".join([url or "", title or "", (content or "")[:400]])
    return bool(_TIMELINE_RE.search(blob))


def _get(obj: Any, key: str, default: Any = "") -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _set_raw_meta(item: Any, **fields: Any) -> None:
    raw = _get(item, "raw_data", None)
    if raw is None or not isinstance(raw, dict):
        raw = {}
    else:
        raw = dict(raw)
    for k, v in fields.items():
        if v is not None:
            raw[k] = v
    if hasattr(item, "raw_data"):
        item.raw_data = raw
    elif isinstance(item, dict):
        item["raw_data"] = raw


def _set_date(item: Any, value: str) -> None:
    if hasattr(item, "date"):
        item.date = value
    elif isinstance(item, dict):
        item["date"] = value


def _published_date_candidates(item: Any) -> list[str]:
    values: list[str] = []
    raw = _get(item, "raw_data", None) or {}
    if isinstance(raw, dict):
        for key in (
            "published_date",
            "release_date",
            "current_version_release_date",
            "currentVersionReleaseDate",
            "pub_date",
        ):
            v = raw.get(key)
            if v:
                values.append(str(v))
        # Avoid treating LLM-written raw_data.date as publish when it may be wrong;
        # only use metrics/source publish fields here.
    metrics = raw.get("metrics") if isinstance(raw, dict) else None
    if isinstance(metrics, dict):
        for key in ("published_date", "release_date", "updated"):
            v = metrics.get(key)
            if v:
                values.append(str(v))
    # Source item published_date may live on the DTO itself via earlier mapping
    return values


def normalize_existing_date(date_str: str) -> str | None:
    text = (date_str or "").strip()
    if not text:
        return None
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return _fmt(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return extract_date_from_text(text)


def compute_temporal_confidence(
    *,
    date_source: str,
    date_semantic: str,
    has_date: bool,
) -> str:
    if not has_date or date_source in (_DATE_SOURCE_NONE, ""):
        return "low"
    if date_source == _DATE_SOURCE_PUBLISHED:
        return "high"
    if date_source == _DATE_SOURCE_PAGE_META:
        return "high"
    if date_source == _DATE_SOURCE_URL:
        return "medium"
    if date_source in (_DATE_SOURCE_SNIPPET_RECENT, _DATE_SOURCE_SNIPPET, _DATE_SOURCE_TITLE):
        return "medium"
    if date_source == _DATE_SOURCE_TIMELINE or date_semantic == _SEMANTIC_EVENT:
        return "low"
    if date_source == _DATE_SOURCE_UNCHANGED:
        if date_semantic == _SEMANTIC_EVENT:
            return "low"
        return "medium"
    return "low"


def format_evidence_date_label(item: Any) -> str:
    """Human-readable date line for digests / evidence lists."""
    date_str = str(_get(item, "date", "") or "").strip()
    raw = _get(item, "raw_data", None) or {}
    semantic = ""
    if isinstance(raw, dict):
        semantic = str(raw.get("date_semantic") or "")
    if not date_str:
        return "日期未知（来源未提供发布时间）"
    if semantic == _SEMANTIC_EVENT:
        return f"事件日期：{date_str}（非页面发布日）"
    return date_str


def _apply_result(
    item: Any,
    *,
    date_value: str | None,
    date_source: str,
    date_semantic: str,
) -> str:
    if date_value:
        _set_date(item, date_value)
    conf = compute_temporal_confidence(
        date_source=date_source if date_value else _DATE_SOURCE_NONE,
        date_semantic=date_semantic if date_value else _SEMANTIC_UNKNOWN,
        has_date=bool(date_value),
    )
    _set_raw_meta(
        item,
        date_source=date_source if date_value else _DATE_SOURCE_NONE,
        date_semantic=date_semantic if date_value else _SEMANTIC_UNKNOWN,
        temporal_confidence=conf,
    )
    # Mirror into quality_score when present
    qs = _get(item, "quality_score", None)
    if isinstance(qs, dict) or qs is None:
        qs = dict(qs or {})
        qs["temporal_confidence"] = conf
        if hasattr(item, "quality_score"):
            item.quality_score = qs
        elif isinstance(item, dict):
            item["quality_score"] = qs
    return date_source if date_value else _DATE_SOURCE_NONE


def enrich_evidence_item(item: Any) -> str:
    """Enrich a single evidence item in place. Returns date_source label."""
    url = str(_get(item, "url", "") or "")
    title = str(_get(item, "title", "") or "")
    content = str(_get(item, "content", "") or "")
    timeline = is_timeline_context(url=url, title=title, content=content)
    raw = _get(item, "raw_data", None) or {}
    existing_source = ""
    if isinstance(raw, dict):
        existing_source = str(raw.get("date_source") or "")

    current = str(_get(item, "date", "") or "").strip()

    # Protect true publish dates from being overwritten by timeline/snippet logic
    if current and existing_source in _PUBLISH_SOURCES:
        normalized = normalize_existing_date(current) or current
        if normalized != current:
            _set_date(item, normalized)
        return _apply_result(
            item,
            date_value=normalized,
            date_source=_DATE_SOURCE_PUBLISHED,
            date_semantic=_SEMANTIC_PUBLISH,
        )

    # Timeline / weak prior date: re-pick most recent from text when possible
    if current and timeline and existing_source not in _PUBLISH_SOURCES:
        recent = extract_date_from_text(content) or extract_date_from_text(title)
        if recent:
            return _apply_result(
                item,
                date_value=recent,
                date_source=_DATE_SOURCE_TIMELINE,
                date_semantic=_SEMANTIC_EVENT,
            )
        normalized = normalize_existing_date(current) or current
        if normalized != current:
            _set_date(item, normalized)
        return _apply_result(
            item,
            date_value=normalized,
            date_source=_DATE_SOURCE_TIMELINE,
            date_semantic=_SEMANTIC_EVENT,
        )

    if current and not timeline:
        # Keep non-empty non-publish dates (e.g. prior LLM) unless weak source wants refresh
        normalized = normalize_existing_date(current) or current
        if normalized != current:
            _set_date(item, normalized)
        src = existing_source or _DATE_SOURCE_UNCHANGED
        if existing_source in (
            _DATE_SOURCE_SNIPPET,
            _DATE_SOURCE_SNIPPET_RECENT,
            _DATE_SOURCE_TITLE,
            _DATE_SOURCE_TIMELINE,
        ):
            # Refresh snippet/title picks with new multi-date policy
            for pub in _published_date_candidates(item):
                parsed = normalize_existing_date(pub) or extract_date_from_text(pub)
                if parsed:
                    return _apply_result(
                        item,
                        date_value=parsed,
                        date_source=_DATE_SOURCE_PUBLISHED,
                        date_semantic=_SEMANTIC_PUBLISH,
                    )
            recent = (
                extract_date_from_url(url)
                or extract_date_from_text(title)
                or extract_date_from_text(content)
            )
            if recent:
                if extract_date_from_url(url) == recent:
                    return _apply_result(
                        item,
                        date_value=recent,
                        date_source=_DATE_SOURCE_URL,
                        date_semantic=_SEMANTIC_PUBLISH,
                    )
                if extract_date_from_text(title) == recent:
                    return _apply_result(
                        item,
                        date_value=recent,
                        date_source=_DATE_SOURCE_TITLE,
                        date_semantic=_SEMANTIC_PUBLISH,
                    )
                return _apply_result(
                    item,
                    date_value=recent,
                    date_source=_DATE_SOURCE_SNIPPET_RECENT,
                    date_semantic=_SEMANTIC_PUBLISH,
                )
        prior_semantic = ""
        if isinstance(raw, dict):
            prior_semantic = str(raw.get("date_semantic") or "") or _SEMANTIC_UNKNOWN
        return _apply_result(
            item,
            date_value=normalized,
            date_source=src if src else _DATE_SOURCE_UNCHANGED,
            date_semantic=prior_semantic if prior_semantic != _SEMANTIC_UNKNOWN else _SEMANTIC_UNKNOWN,
        )

    # Empty date — fill in priority order
    for pub in _published_date_candidates(item):
        parsed = normalize_existing_date(pub) or extract_date_from_text(pub)
        if parsed:
            return _apply_result(
                item,
                date_value=parsed,
                date_source=_DATE_SOURCE_PUBLISHED,
                date_semantic=_SEMANTIC_PUBLISH,
            )

    parsed = extract_date_from_url(url)
    if parsed:
        return _apply_result(
            item,
            date_value=parsed,
            date_source=_DATE_SOURCE_URL,
            date_semantic=_SEMANTIC_PUBLISH,
        )

    parsed = extract_date_from_text(title)
    if parsed:
        if timeline:
            return _apply_result(
                item,
                date_value=parsed,
                date_source=_DATE_SOURCE_TIMELINE,
                date_semantic=_SEMANTIC_EVENT,
            )
        return _apply_result(
            item,
            date_value=parsed,
            date_source=_DATE_SOURCE_TITLE,
            date_semantic=_SEMANTIC_PUBLISH,
        )

    parsed = extract_date_from_text(content)
    if parsed:
        if timeline:
            return _apply_result(
                item,
                date_value=parsed,
                date_source=_DATE_SOURCE_TIMELINE,
                date_semantic=_SEMANTIC_EVENT,
            )
        return _apply_result(
            item,
            date_value=parsed,
            date_source=_DATE_SOURCE_SNIPPET_RECENT,
            date_semantic=_SEMANTIC_PUBLISH,
        )

    return _apply_result(
        item,
        date_value=None,
        date_source=_DATE_SOURCE_NONE,
        date_semantic=_SEMANTIC_UNKNOWN,
    )


def enrich_evidence_dates(items: list[Any] | None) -> list[Any]:
    """Enrich all items in place; return the same list."""
    if not items:
        return items or []
    for item in items:
        enrich_evidence_item(item)
    return items
