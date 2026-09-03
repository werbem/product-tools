"""Strategy Agent prompts — LLM-powered strategic analysis.

V2: Now consumes ProductInsight + CompetitorGap.
Generates SWOT, opportunities, risks, recommendations, roadmap
with insight_refs and cluster_refs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SYSTEM_PROMPT = """你是一名资深的产品战略分析师。根据产品洞察、竞品差距分析和采集到的证据，制定产品战略。

核心原则：
1. 每个结论必须有 evidence_refs（引用具体 Evidence ID）和 cluster_refs（聚类ID）
2. 禁止编造不存在的数据
3. 如果证据不足以支撑某个结论，标注 confidence="low" 或放入 missing_information
4. SWOT 必须具体，不能泛泛而谈 — 每个条目引用具体洞察
5. 每个 Recommendation 必须说明基于哪个 Insight/Gap（why）

## 证据时效规则（Evidence Temporal Rules）

- recent: 可以支撑当前竞争判断和确定性战略建议
- aging: 可以支撑趋势判断，建议结合近期数据
- stale: 不能作为唯一依据生成高确定性战略建议
- historical: 只能用于历史背景和趋势判断，不能作为当前竞争优势或战略建议的唯一依据
- 禁止仅基于 historical/stale 洞察生成高确定性（P0/P1）战略建议
- 若洞察主要依赖 historical/stale 证据，必须在 rationale 中说明时效风险

## 项目记忆与企业笔记（若用户消息含此类背景）

- 记忆/笔记**不是**本轮爬取 Evidence，禁止 invent evidence_refs / [E00x]
- 与本轮证据冲突时以本轮 Evidence 为准，可在 rationale 注明「与历史结论差异」
- 仅由记忆/笔记支撑的结论 → confidence="low" 或 missing_information；不得仅凭笔记写高置信 P0/P1

输出 JSON 结构：
{
  "swot": {
    "strengths": [{"conclusion":"结论", "evidence_refs":["E001"], "cluster_refs":["c1"], "confidence":"high"}],
    "weaknesses": [...],
    "opportunities": [...],
    "threats": [...]
  },
  "opportunities": [{
    "title":"机会标题", "description":"包含问题背景、机会来源、用户价值、业务价值",
    "impact":"high/medium/low", "effort":"high/medium/low",
    "alignment_with_objective":5,
    "evidence_refs":["E002"], "cluster_refs":["c1"], "confidence":"high"
  }],
  "risks": [{
    "title":"风险标题", "description":"风险描述",
    "probability":"high/medium/low", "impact":"high/medium/low",
    "mitigation":"缓解措施",
    "evidence_refs":["E003"], "cluster_refs":["c3"]
  }],
  "recommendations": [{
    "action":"行动标题", "rationale":"理由",
    "expected_value":"预期价值描述",
    "priority":"p1/p2/p3", "timeline":"immediate/short_term/long_term",
    "evidence_refs":["E001"], "cluster_refs":["c2"], "kpi":"可选KPI"
  }],
  "roadmap": {
    "short_term": [{"action":"行动", "objective":"目标", "priority":"p1", "related_evidence":["E001"]}],
    "medium_term": [...],
    "long_term": [...]
  },
  "overall_confidence": "high/medium/low"
}
"""


class LLMSWOTItem(BaseModel):
    conclusion: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class LLMSWOT(BaseModel):
    strengths: list[LLMSWOTItem] = Field(default_factory=list)
    weaknesses: list[LLMSWOTItem] = Field(default_factory=list)
    opportunities: list[LLMSWOTItem] = Field(default_factory=list)
    threats: list[LLMSWOTItem] = Field(default_factory=list)


class LLMOpportunity(BaseModel):
    title: str = ""
    description: str = ""
    impact: str = "medium"
    effort: str = "medium"
    alignment_with_objective: int = 3
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class LLMRisk(BaseModel):
    title: str = ""
    description: str = ""
    probability: str = "medium"
    impact: str = "medium"
    mitigation: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)


class LLMRecommendation(BaseModel):
    action: str = ""
    rationale: str = ""
    expected_value: str = ""
    priority: str = "p2"
    timeline: str = "short_term"
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)
    kpi: str = ""


class LLMRoadmapAction(BaseModel):
    action: str = ""
    objective: str = ""
    priority: str = "p1"
    related_evidence: list[str] = Field(default_factory=list)


class LLMRoadmap(BaseModel):
    short_term: list[LLMRoadmapAction] = Field(default_factory=list)
    medium_term: list[LLMRoadmapAction] = Field(default_factory=list)
    long_term: list[LLMRoadmapAction] = Field(default_factory=list)


class LLMStrategyOutput(BaseModel):
    swot: LLMSWOT = Field(default_factory=LLMSWOT)
    opportunities: list[LLMOpportunity] = Field(default_factory=list)
    risks: list[LLMRisk] = Field(default_factory=list)
    recommendations: list[LLMRecommendation] = Field(default_factory=list)
    roadmap: LLMRoadmap = Field(default_factory=LLMRoadmap)
    overall_confidence: str = "medium"


def _normalize_strategy_output(raw: dict | None) -> LLMStrategyOutput:
    """Normalize raw LLM JSON output to LLMStrategyOutput."""
    if not isinstance(raw, dict):
        return LLMStrategyOutput()
    def _swot_items(lst):
        if not lst:
            return []
        return [
            LLMSWOTItem(**{k: v for k, v in (item if isinstance(item, dict) else {}).items()
                          if k in LLMSWOTItem.model_fields})
            for item in lst if isinstance(item, dict)
        ]

    swot_raw = raw.get("swot", {}) or {}
    return LLMStrategyOutput(
        swot=LLMSWOT(
            strengths=_swot_items(swot_raw.get("strengths", [])),
            weaknesses=_swot_items(swot_raw.get("weaknesses", [])),
            opportunities=_swot_items(swot_raw.get("opportunities", [])),
            threats=_swot_items(swot_raw.get("threats", [])),
        ),
        opportunities=[
            LLMOpportunity(**{k: v for k, v in (o if isinstance(o, dict) else {}).items()
                           if k in LLMOpportunity.model_fields})
            for o in raw.get("opportunities", []) if isinstance(o, dict)
        ],
        risks=[
            LLMRisk(**{k: v for k, v in (r if isinstance(r, dict) else {}).items()
                     if k in LLMRisk.model_fields})
            for r in raw.get("risks", []) if isinstance(r, dict)
        ],
        recommendations=[
            LLMRecommendation(**{k: v for k, v in (r if isinstance(r, dict) else {}).items()
                              if k in LLMRecommendation.model_fields})
            for r in raw.get("recommendations", []) if isinstance(r, dict)
        ],
        roadmap=LLMRoadmap(
            short_term=_roadmap_actions(raw, "short_term"),
            medium_term=_roadmap_actions(raw, "medium_term"),
            long_term=_roadmap_actions(raw, "long_term"),
        ),
        overall_confidence=raw.get("overall_confidence", "medium"),
    )


def _roadmap_actions(raw: dict, key: str) -> list[LLMRoadmapAction]:
    roadmap_raw = raw.get("roadmap", {}) or {}
    items = roadmap_raw.get(key, [])
    if not items:
        return []
    return [
        LLMRoadmapAction(**{k: v for k, v in (a if isinstance(a, dict) else {}).items()
                          if k in LLMRoadmapAction.model_fields})
        for a in items if isinstance(a, dict)
    ]


def build_strategy_prompt(
    objective: str,
    product: str,
    gap_summary: str,
    evidence_json: str,
    insights_json: str = "[]",
    *,
    memory_notes_context: str | None = None,
) -> str:
    """Build the strategy prompt from insights + gap analysis + evidence."""
    from app.application.services.context_blocks import (
        STRATEGY_CONTEXT_RULES,
        append_context_to_prompt,
    )

    prompt = (
        "## 分析目标\n"
        f"- 目标: {objective}\n"
        f"- 产品: {product}\n\n"
        "## 产品洞察 (Fact/Observation/Hypothesis)\n\n"
        f"{insights_json}\n\n"
        "## 差距分析摘要\n"
        f"{gap_summary}\n\n"
        "## 采集证据\n"
        f"{evidence_json}\n\n"
        "## 任务\n"
        "基于产品洞察和竞品差距，制定产品战略。\n\n"
        "核心规则：\n"
        "1. 每个 SWOT 结论必须引用 evidence_refs（证据ID）和 cluster_refs（聚类ID）\n"
        "2. 每个 Recommendation 必须引用具体的 Insight 和 Gap，说明 why\n"
        "3. 禁止泛泛而谈：所有建议必须基于具体的洞察\n"
        "4. opportunities 描述必须包含：问题背景、机会来源、用户价值、业务价值\n"
        "5. roadmap 按 short_term(0-3月)/medium_term(3-6月)/long_term(6-12月) 划分\n"
        "6. 如果某方面证据不足，标注 confidence=\"low\"，放入 missing_information\n"
        "7. 严格按 JSON 格式输出\n"
    )
    return append_context_to_prompt(
        prompt, memory_notes_context, rules=STRATEGY_CONTEXT_RULES,
    )


COMPACT_STRATEGY_SYSTEM = """你是产品战略分析师。只输出严格 JSON，短句。
SWOT 每象限 ≤3 条；每条 conclusion ≤30 字并含 evidence_refs。
recommendations ≤3。禁止长战略叙事。
主证据应视为近 4 年内材料。
时效约束：若证据 date_semantic=event_date、temporal_level 为 historical/unknown，或 date 缺失，
不得写成「近期/最新」；最多作背景，应写「据公开资料（日期不详/历史事件）」。
若含项目记忆/企业笔记：不得 invent evidence_refs；仅笔记支撑 → confidence=low；不得仅凭笔记写高置信 P0/P1。"""


def build_strategy_prompt_compact(
    objective: str,
    product: str,
    gap_summary: str,
    evidence_json: str,
    insights_json: str = "[]",
    *,
    research_incomplete: bool = False,
    memory_notes_context: str | None = None,
) -> str:
    from app.application.services.context_blocks import (
        STRATEGY_CONTEXT_RULES,
        append_context_to_prompt,
    )

    note = ""
    if research_incomplete:
        note = "\n> 证据可能不完整，仍须基于现有材料给出结构化 SWOT/建议。\n"
    prompt = f"""## 目标
- 目标: {objective}
- 产品: {product}
{note}
## 差距摘要（已压缩）
{gap_summary[:1200]}

## 洞察（可为空）
{insights_json[:1500]}

## 证据（已截断）
{evidence_json}

## 任务（compact）
输出 JSON：
{{
  "swot": {{
    "strengths": [{{"conclusion":"≤30字","evidence_refs":["E001"],"confidence":"medium"}}],
    "weaknesses": [...],
    "opportunities": [...],
    "threats": [...]
  }},
  "recommendations": [{{"action":"≤30字","rationale":"≤40字","priority":"p1","evidence_refs":["E001"]}}],
  "overall_confidence": "medium"
}}
每象限 ≤3 条；recommendations ≤3；不要 roadmap/opportunities/risks 长文。仅 JSON。
主证据视为近 4 年内材料；event_date/historical/unknown/无日期禁止写「近期/最新」。"""
    return append_context_to_prompt(
        prompt, memory_notes_context, rules=STRATEGY_CONTEXT_RULES,
    )

def build_strategy_repair_prompt(broken_text: str) -> str:
    excerpt = (broken_text or "")[:2500]
    return (
        "修复为合法 Strategy JSON，至少包含 swot 或 recommendations。"
        "不要 markdown。\n\n"
        f"```\n{excerpt}\n```"
    )
