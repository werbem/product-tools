"""Format collection workflow output as readable markdown (no LLM)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.application.services.collection_topic import resolve_collection_topic_from_state
from app.infrastructure.tools.evidence_date import format_evidence_date_label


def build_collection_markdown(state: dict[str, Any]) -> str:
    """Build an evidence digest from internal workflow state."""
    validated = state.get("validated_input") or {}
    user_input = state.get("user_input") or {}
    company = validated.get("our_company") or user_input.get("our_company") or "目标主体"
    product = validated.get("product") or user_input.get("product") or ""

    topic_info = resolve_collection_topic_from_state(state)
    topic = topic_info["topic"]

    evidence_items = (state.get("evidence_bundle") or {}).get("evidence_items") or []
    meta = state.get("collection_meta") or {}
    quality = state.get("quality_report") or {}

    title = f"{company} · {product} 信息收集摘要" if product else f"{company} 信息收集摘要"
    lines = [
        f"# {title}",
        "",
        f"> **收集主题**：{topic}",
        f"> **生成时间**：{datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]

    sources_ok = meta.get("sources_succeeded", quality.get("sources_succeeded", 0))
    sources_total = meta.get("sources_attempted", quality.get("sources_attempted", 0))
    lines.append(
        f"共检索 **{sources_total}** 路数据源（成功 {sources_ok} 路），"
        f"整理 **{len(evidence_items)}** 条有效信息。"
    )
    lines.append("")

    warnings = list(meta.get("warnings") or []) + list(quality.get("missing_data_warnings") or [])
    if warnings:
        lines.append("## 说明")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    if not evidence_items:
        lines.append("_未收集到可用公开信息，请稍后重试或调整关键词。_")
        return "\n".join(lines)

    lines.append("## 信息条目")
    lines.append("")
    for idx, item in enumerate(evidence_items, start=1):
        title_text = item.get("title") or f"条目 {idx}"
        url = item.get("url") or ""
        source = item.get("source") or item.get("source_type") or "web"
        date = format_evidence_date_label(item)
        content = (item.get("content") or "").strip()
        confidence = item.get("confidence") or "medium"
        eid = item.get("id") or f"E{idx:03d}"

        lines.append(f"### {idx}. {title_text}")
        lines.append("")
        lines.append(f"- **编号**：{eid}")
        lines.append(f"- **来源**：{source}")
        lines.append(f"- **日期**：{date}")
        lines.append(f"- **可信度**：{confidence}")
        if url:
            lines.append(f"- **链接**：{url}")
        lines.append("")
        if content:
            snippet = content if len(content) <= 600 else content[:600] + "…"
            lines.append(snippet)
            lines.append("")

    lines.append("---")
    lines.append("*本摘要由信息收集工作流自动生成，仅包含公开检索结果，不含竞品对比或战略建议。*")
    return "\n".join(lines)


def build_collection_document_meta(state: dict[str, Any]) -> dict[str, Any]:
    """Topic fields to persist alongside markdown (backward compatible)."""
    topic_info = resolve_collection_topic_from_state(state)
    return {
        "topic": topic_info["topic"],
        "topic_source": topic_info["topic_source"],
        "objective_code": topic_info.get("objective_code") or "",
    }
