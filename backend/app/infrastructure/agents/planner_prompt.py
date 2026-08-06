"""Planner Agent prompts — used by the LLM to generate ResearchPlan."""

from __future__ import annotations

from pydantic import BaseModel, Field


SYSTEM_PROMPT = """你是一名互联网战略分析专家，专注于竞品研究。

你的核心职责：针对指定公司完成精准的竞品分析，而非生成泛泛的行业报告。

## 研究规则

1. **聚焦目标公司**：所有搜索关键词必须包含目标公司名称和产品名称
2. **禁止行业泛搜**：不要搜索"旅游行业趋势""互联网发展"等无法直接关联目标公司的泛词
3. **关键搜索词格式**：
   - 正确：飞猪 APP DAU下降 2026、飞猪 用户增长 放缓、美团旅行 酒店业务 竞争
   - 错误：旅游行业 用户下降 原因、在线旅游 市场分析
4. **分析与竞品对比**：如果提供了竞品公司，必须同时搜索双方的对比信息
5. **重视时效性**：优先搜索近期（一年内）的信息

## 分析维度

必须从以下维度中选择（至少3个，不超过8个）：
- 用户增长（DAU/MAU变化、用户结构）
- 产品功能（功能变化、产品体验）
- 商业模式（定价、变现）
- 运营策略（活动、渠道）
- 市场竞争（竞品动作、市场份额）
- 技术能力
- 政策监管
- 品牌口碑

请输出结构化的 JSON 格式。"""


class LLMResearchPlanOutput(BaseModel):
    """Structured output that the LLM returns — maps to ResearchPlan."""
    analysis_goal: str = Field(description="分析目标的一句话总结，例如「分析飞猪DAU持续下降的根因」")
    research_dimensions: list[str] = Field(
        description="需要分析的研究维度列表（至少3个，不超过8个）。"
                    "必须使用中文输出。"
                    "例如：['用户画像与行为变化', '核心功能对比', '商业模式差异', '增长策略与市场']",
    )
    search_keywords: list[str] = Field(
        description="搜索关键词列表，用于跨源证据采集。"
                    "每个关键词应该具体、可搜索。例如：['飞猪 DAU 下降 原因', '携程 用户增长 策略']",
    )
    priority: int = Field(
        ge=1, le=5,
        description="研究优先级：1最低，5最高。"
                    "根据问题的紧迫性和业务影响判断。",
    )
    estimated_complexity: str = Field(
        description="研究复杂度评估：'simple'（单一维度问题）、'moderate'（多维度、需对比分析）、'complex'（多公司、多市场、多维度深度研究）",
    )


def build_user_prompt(
    our_company: str,
    competitor_company: str,
    product: str,
    objective: str,
    optional_context: str | None = None,
) -> str:
    """Build the user prompt for the LLM."""
    objective_labels = {
        "product_improvement": "产品改进 — 对标竞品发现自身短板，制定迭代方向",
        "go_to_market": "市场进入 — 了解竞品格局，制定差异化定位与策略",
        "investment_due_diligence": "投资尽调 — 评估标的公司的产品竞争壁垒与风险",
        "competitive_defense": "竞争防御 — 应对竞品进攻，评估威胁并制定防守策略",
        "positioning_switch": "定位转型 — 重新定义产品定位时，需要全面竞争格局分析",
        "partnership_evaluation": "合作评估 — 考察竞品是否可作为生态合作伙伴",
        "feature_benchmark": "功能对标 — 针对具体功能模块做深度对比",
    }

    obj_label = objective_labels.get(objective, objective)

    prompt = f"""## 分析需求

- **我方公司**: {our_company}
- **竞品公司**: {competitor_company}
- **分析产品**: {product}
- **分析目标**: {obj_label}
- **用户描述**: {objective if objective not in objective_labels else ''}
"""

    if optional_context:
        prompt += f"\n- **补充背景**: {optional_context}\n"

    prompt += """
请根据以上需求，制定一份研究计划。注意：
1. research_dimensions 必须至少3个，且有实质内容
2. search_keywords 应该具体可搜索，至少5个
3. priority 根据问题紧迫性判断
4. estimated_complexity 根据问题范围判断
"""

    return prompt
