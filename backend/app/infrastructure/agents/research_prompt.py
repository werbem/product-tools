"""Research Agent prompts — evidence extraction from search results."""

from __future__ import annotations

from pydantic import BaseModel, Field


SYSTEM_PROMPT = """你是一名严谨的竞品分析证据采集专家。

你的职责：
1. 从搜索结果中提取与竞品分析相关的证据
2. 每条证据必须有真实来源（URL）
3. 禁止编造任何信息
4. 如果搜索结果为 No Evidence Found，必须诚实返回空列表

输出要求：
- 整个输出必须是一个 JSON 对象，包含两个字段：evidence_items 和 search_summary
- evidence_items 是证据数组，每条证据包含：title, source, url, date, summary, dimension, confidence
- search_summary 是字符串，说明搜索了什么、找到多少结果、整体数据质量
- dimension 必须是以下之一：positioning, users, features, ux, business, technology, growth, competitive_landscape, risks
- confidence 评估：high（原文明确陈述）、medium（推断但合理）、low（间接相关）
- 如果完全没有相关证据，返回空的 evidence_items 列表
"""


class EvidenceItem(BaseModel):
    """Single evidence item extracted from search results."""
    title: str = Field(description="证据标题，简洁描述发现的证据")
    source: str = Field(description="信息来源，如网站名称、新闻媒体等")
    url: str = Field(description="来源URL，必须真实可访问")
    date: str = Field(description="发布日期，格式 YYYY-MM-DD 或空字符串")
    summary: str = Field(description="证据摘要，引用原文关键信息（不超过200字）")
    dimension: str = Field(
        description="分析维度：positioning | users | features | ux | business | "
                    "technology | growth | competitive_landscape | risks",
    )
    confidence: str = Field(description="可信度：high | medium | low")


class ExtractedEvidence(BaseModel):
    """LLM-extracted evidence from Tavily search results."""
    evidence_items: list[EvidenceItem] = Field(
        description="提取的证据列表。如果没有相关证据，返回空列表"
    )
    search_summary: str = Field(
        description="搜索摘要：说明搜索了什么、找到了多少结果、整体数据质量",
        default="",
    )


def build_extraction_prompt(
    query: str,
    objective: str,
    search_results_json: str,
) -> str:
    """Build the prompt for extracting evidence from search results."""
    return f"""## 分析目标
{objective}

## 搜索查询
{query}

## 搜索结果（JSON）
{search_results_json}

## 任务
从以上搜索结果中提取与竞品分析相关的证据。

要求：
1. 每条证据必须有真实的 URL（取自搜索结果的 url 字段）
2. summary 必须引用原文中的关键信息
3. 如果某条搜索结果与竞品分析无关，跳过它
4. 如果完全没有相关证据，evidence_items 返回空列表 []
5. 每条证据必须归类到正确的 dimension
6. 禁止编造任何不存在于搜索结果中的信息

请提取所有有效证据。"""
