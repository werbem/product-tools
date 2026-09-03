"""Insight Agent prompts — Fact/Observation/Hypothesis generation."""

from __future__ import annotations

from pydantic import BaseModel, Field


SYSTEM_PROMPT = """你是产品策略洞察分析师。从证据聚类和竞品差距中生成结构化洞察。

## 洞察类型（严格区分）

### Fact（事实）
- 基于已有证据的直接结论
- 必须有明确的 evidence_refs 和 cluster_refs
- 不允许推测

### Observation（观察）
- 从多个 Fact 中总结的趋势判断
- 需要引用支撑的 cluster
- 可以有合理推断，但不能编造数据

### Hypothesis（假设）
- 基于证据链的产品推断
- 必须标注 confidence（low/medium/high）
- 假设如果 confidence=low 但有启发意义，仍可输出

## 核心原则
1. 每个洞察必须引用 cluster_refs 和 evidence_refs
2. 禁止无证据推理
3. 事实不编造、观察有依据、假设有推测基础
4. 按 impact 排序：high > medium > low
5. 每种类型至少生成 1 条（如果证据充分）

## Evidence Temporal Rules

- recent: 支持当前竞争分析和洞察
- aging: 支持趋势分析
- stale: 不能作为唯一依据形成高影响判断
- historical: 只能描述历史演变，不能支撑当前竞争优势判断
- historical 不能作为当前市场判断的唯一依据
- hypothesis 不得仅依赖 historical/stale 证据
- 若缺少近期数据，需要在洞察描述中明确说明

## 输出格式 (JSON)

{
  "insights": [
    {
      "title": "用户对飞猪价格竞争力不满",
      "type": "fact",
      "description": "根据App Store评论和知乎讨论，用户普遍认为飞猪价格高于美团",
      "evidence_refs": ["e8", "e12"],
      "cluster_refs": ["c3"],
      "confidence": "high",
      "impact": "high",
      "dimension": "pricing"
    }
  ],
  "summary": "一句话总结所有洞察"
}
"""


class InsightItem(BaseModel):
    title: str = ""
    type: str = "fact"  # fact | observation | hypothesis
    description: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)
    confidence: str = "medium"
    impact: str = "medium"
    dimension: str = ""


class LLMInsightOutput(BaseModel):
    insights: list[InsightItem] = Field(default_factory=list)
    summary: str = ""


def build_flat_insight_prompt(
    our_company: str,
    competitor_company: str,
    product: str,
    objective: str,
    evidence_json: str,
    gaps_json: str,
) -> str:
    return f"""## 分析场景
- 我方: {our_company} / {product}
- 竞品: {competitor_company} / {product}
- 目标: {objective}

## 扁平证据列表（无聚类时的轻量路径）

{evidence_json}

## 竞品差距分析（可能为空或超时 stub）

{gaps_json}

## 任务
1. 从证据中提取 Fact（事实）
2. 从多条事实中总结 Observation（趋势判断）
3. 基于证据链提出 Hypothesis（产品推断）

每个洞察必须包含 evidence_refs；cluster_refs 可为空数组。
三种类型各至少生成 1 条（如果证据充分）。

请输出 JSON。"""


def build_insight_prompt(
    our_company: str,
    competitor_company: str,
    product: str,
    objective: str,
    clusters_json: str,
    gaps_json: str,
) -> str:
    return f"""## 分析场景
- 我方: {our_company} / {product}
- 竞品: {competitor_company} / {product}
- 目标: {objective}

## 证据主题聚类

{clusters_json}

## 竞品差距分析

{gaps_json}

## 任务
1. 从证据聚类中提取 Fact（事实）
2. 从多组事实中总结 Observation（趋势判断）
3. 基于证据链提出 Hypothesis（产品推断）

每个洞察必须包含 cluster_refs 和 evidence_refs。
三种类型各至少生成 1 条（如果证据充分）。

请输出 JSON。"""
