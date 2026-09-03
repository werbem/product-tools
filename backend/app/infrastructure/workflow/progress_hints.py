"""Stage hint copy for workflow progress (Fast / Full)."""

from __future__ import annotations

NO_EVIDENCE_CLUSTERING_HINT = "证据不足，跳过聚类，继续分析…"
RAW_TIMEOUT_FALLBACK_HINT = "检索已完成，抽取超时，已用原始搜索结果继续分析…"
COMPARE_TIMEOUT_STUB_HINT = "对比超时，已用证据摘要继续…"
STRATEGY_TIMEOUT_STUB_HINT = "策略超时，已用证据摘要继续…"

RESEARCH_PROGRESS_HINTS: dict[float, str] = {
    20.0: "正在检索公开信息…",
    24.0: "正在选择信息源…",
    28.0: "正在搜索网页…",
    32.0: "正在分析网页内容…",
    36.0: "正在整理证据…",
    40.0: "研究完成",
    42.0: "正在聚类整理证据…",
    44.0: "证据整理完成",
}

FAST_REPORT_SEGMENT_HINTS: dict[int, str] = {
    1: "正在撰写报告（第 1 部分）…",
    2: "正在撰写报告（第 2 部分）…",
    3: "正在撰写报告（第 3 部分）…",
}

FAST_REPORT_DONE_HINT = "报告生成完成"

FULL_PHASE_ENTRY_HINTS: dict[str, tuple[float, str]] = {
    "compare": (45.0, "正在对比分析…"),
    "insight": (55.0, "正在生成洞察…"),
    "strategy": (65.0, "正在制定策略…"),
    "report": (72.0, "正在撰写报告…"),
    "review": (90.0, "正在审阅报告…"),
}

PHASE_COMPLETION_HINTS: dict[str, str] = {
    "researched": "研究完成",
    "compared": "对比分析完成",
    "insighted": "洞察生成完成",
    "strategized": "策略制定完成",
    "reported": "报告生成完成",
    "reviewed": "审阅完成",
}
