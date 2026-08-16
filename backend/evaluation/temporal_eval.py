"""Temporal compliance + evidence freshness metrics."""

from __future__ import annotations

import re
from datetime import datetime

from evaluation.models import MetricResult


_FRESHNESS_WEIGHTS = {
    "recent": 1.0,
    "aging": 0.75,
    "mixed": 0.5,
    "unknown": 0.5,
    "stale": 0.25,
    "historical": 0.1,
}

_MARKDOWN_VIOLATION_KEYWORDS = [
    # 竞争状态
    "当前领先", "市场第一", "占据优势", "强势地位", "明显领先",
    # 当前指标
    "用户规模", "当前价格", "当前份额", "当前增长",
    # 当前能力
    "已成为", "领先于", "优于",
]


def _get_temporal_level(evidence: dict) -> str:
    """Read temporal_level from quality_score; fall back to date year."""
    qs = evidence.get("quality_score") or {}
    level = qs.get("temporal_level", "") if isinstance(qs, dict) else ""
    if level:
        return level
    date_str = evidence.get("date", "") or ""
    if not date_str:
        return "unknown"
    m = re.search(r"(20\d{2})", str(date_str))
    if not m:
        return "unknown"
    age = datetime.now().year - int(m.group(1))
    if age < 1:
        return "recent"
    if age < 3:
        return "aging"
    if age < 5:
        return "stale"
    return "historical"


def evidence_freshness(evidence_items: list[dict]) -> MetricResult:
    """Metric 5: weighted temporal distribution (0-100)."""
    dist: dict[str, int] = {}
    for e in evidence_items:
        level = _get_temporal_level(e)
        dist[level] = dist.get(level, 0) + 1
    total = len(evidence_items)
    if total == 0:
        return MetricResult(100.0, {"total": 0, "distribution": {}})
    weighted = sum(
        _FRESHNESS_WEIGHTS.get(level, 0.5) * count
        for level, count in dist.items()
    )
    score = round(weighted / total * 100, 2)
    return MetricResult(score, {"total": total, "distribution": dist})


def temporal_compliance(
    evidence_items: list[dict],
    insights: list[dict],
    recommendations: list[dict],
    markdown: str,
) -> MetricResult:
    """Metric 1 V1.1: 0.5 * structured_score + 0.5 * markdown_score."""
    evidence_map: dict[str, str] = {}
    for e in evidence_items:
        eid = e.get("id", "") or e.get("source_id", "")
        if eid:
            evidence_map[str(eid)] = _get_temporal_level(e)

    # ── Part 1: structured compliance ──
    historical_refs = 0
    bad_structured_usage = 0
    bad_usage_details: list[dict] = []

    for ins in insights:
        ins_type = ins.get("type", "")
        for ref in (ins.get("evidence_refs", []) or []):
            level = evidence_map.get(str(ref), "")
            if level in ("historical", "stale"):
                historical_refs += 1
                if ins_type in ("fact", "observation"):
                    bad_structured_usage += 1
                    bad_usage_details.append({
                        "ref": ref, "level": level, "context": f"insight:{ins_type}",
                    })

    for rec in recommendations:
        for ref in (rec.get("evidence_refs", []) or []):
            level = evidence_map.get(str(ref), "")
            if level in ("historical", "stale"):
                historical_refs += 1
                bad_structured_usage += 1
                bad_usage_details.append({
                    "ref": ref, "level": level, "context": "recommendation",
                })

    structured_score = 100.0
    if historical_refs > 0:
        structured_score = max(
            0.0,
            min(100.0, round(100 * (1 - bad_structured_usage / historical_refs), 2)),
        )

    # ── Part 2: markdown compliance ──
    markdown_historical_refs = 0
    markdown_bad_usage = 0
    markdown_warnings: list[str] = []
    if markdown:
        for ref, level in evidence_map.items():
            if level not in ("historical", "stale"):
                continue
            pattern = f"[{ref}]"
            for m in re.finditer(re.escape(pattern), markdown):
                markdown_historical_refs += 1
                window = markdown[max(0, m.start() - 40):m.end() + 40]
                if any(kw in window for kw in _MARKDOWN_VIOLATION_KEYWORDS):
                    markdown_bad_usage += 1
                    markdown_warnings.append(
                        f"历史证据 {ref}({level}) 附近出现当前确定性表达"
                    )

    markdown_score = 100.0
    if markdown_historical_refs > 0:
        markdown_score = max(
            0.0,
            min(100.0, round(100 * (1 - markdown_bad_usage / markdown_historical_refs), 2)),
        )

    # ── Combined ──
    score = round(structured_score * 0.5 + markdown_score * 0.5, 2)

    return MetricResult(
        score,
        {
            "structured_score": structured_score,
            "markdown_score": markdown_score,
            "structured_bad_usage_count": bad_structured_usage,
            "structured_historical_reference_count": historical_refs,
            "markdown_bad_usage_count": markdown_bad_usage,
            "markdown_historical_reference_count": markdown_historical_refs,
            "bad_usage": bad_usage_details,
            "markdown_warnings": markdown_warnings,
        },
    )
