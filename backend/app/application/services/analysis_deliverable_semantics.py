"""Analysis-deliverable semantics for Intent layer (not Router priority hacks).

Approved vocabulary (A/B + C1–C4):
- A: 竞品调研报告 / 调研报告 / 研究报告 / 尽调报告 …
- B: 对标 / EN research|intelligence|benchmarking report
- C1 市场调研报告 → analyze
- C2 行业研究报告 → analyze
- C3-1 竞品情报报告 → analyze；C3-2 竞品情报摘要 → collect（本模块不命中）
- C4 调研竞品并出报告 → analyze

Anti-examples stay collect via existing collection-primary / bare 调研动态 paths.
"""

from __future__ import annotations

import re

# Digest / summary asks must NOT be treated as analysis deliverables (C3-2).
_COLLECTION_DIGEST_PATTERN = re.compile(
    r"情报摘要|信息摘要|资料摘要|收集摘要|竞品摘要",
    re.IGNORECASE,
)

# Explicit analysis / CA-style deliverables (report, peer benchmark, diligence).
_ANALYSIS_DELIVERABLE_PATTERN = re.compile(
    r"竞品调研报告|竞争调研报告|市场调研报告|行业调研报告|"
    r"行业研究报告|竞品研究报告|研究报告|"
    r"调研报告|"
    r"深度竞品研究|竞品研究.{0,12}报告|"
    r"竞品尽调|尽调报告|尽职调查报告|"
    r"竞品对标分析|对标分析|竞品对标|"
    r"(?:帮我|请|麻烦)?对标(?:一下|下)?"
    r"|竞品情报报告|"
    r"调研竞品.{0,16}(?:并)?(?:出|做|写|生成)?报告|"
    r"调研.{0,12}竞品.{0,16}报告|"
    r"competitive\s+intelligence\s+report|"
    r"competitor\s+research\s+report|"
    r"market\s+research\s+report|"
    r"industry\s+research\s+report|"
    r"benchmarking\s+report",
    re.IGNORECASE,
)


def looks_like_collection_digest(text: str | None) -> bool:
    """True for summary/digest asks that should stay on the collect path."""
    return bool(text and _COLLECTION_DIGEST_PATTERN.search(text))


def looks_like_analysis_deliverable(text: str | None) -> bool:
    """True when the user asks for an analysis-style deliverable (report/benchmark)."""
    text = (text or "").strip()
    if not text:
        return False
    if looks_like_collection_digest(text):
        return False
    return bool(_ANALYSIS_DELIVERABLE_PATTERN.search(text))


def matched_analysis_deliverable_signals(text: str | None) -> list[str]:
    text = text or ""
    if looks_like_collection_digest(text):
        return []
    return [m.group(0) for m in _ANALYSIS_DELIVERABLE_PATTERN.finditer(text)]
