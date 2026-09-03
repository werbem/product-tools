"""Planner Agent — generates Research Plan via LLM.

Uses real LLM (OpenAI) to dynamically generate research plans based on input.
Falls back to mock when LLM is unavailable.
"""

from __future__ import annotations

from datetime import datetime

from app.application.dto.agent_dto import (
    PlannerInput,
    PlannerOutput,
    ResearchPlan,
    ResearchTask,
)
from app.config.constants import Phase
from app.infrastructure.agents.base import AgentContext, AgentResult, BaseAgent
from app.infrastructure.agents.planner_prompt import (
    LLMResearchPlanOutput,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.infrastructure.llm.client import llm_client


# ── Source type definitions ──

_SOURCE_TYPES = [
    "web",
    "news",
    "app_store",
    "social",
]

_SOURCE_PRIORITY_BOOST = {
    "web": 0,
    "news": 0,
    "app_store": -1,
    "social": -1,
}

_SOURCE_KEYWORD_SUFFIX = {
    "web": "",
    "news": " 新闻",
    "app_store": " App",
    "social": " 讨论",
}

_WORKFLOW_STEPS = [
    "research",
    "compare",
    "strategy",
    "report",
    "review",
]

# ── English dimension → Chinese dimension normalization ──
# DeepSeek/LLM frequently returns English dimension names (positioning, users,
# business, ...) which do not match the Chinese keyword rules used by the
# source selection engine. Normalize them back to Chinese so that both the
# LLM router prompt and the rule-based fallback can match correctly.

_DIMENSION_ZH_MAP: dict[str, str] = {
    "user growth": "用户增长（DAU/MAU变化）",
    "user_growth": "用户增长（DAU/MAU变化）",
    "usergrowth": "用户增长（DAU/MAU变化）",
    "positioning": "产品定位与品牌",
    "users": "用户画像与行为变化",
    "user": "用户画像与行为变化",
    "growth": "增长策略与市场",
    "business model": "商业模式差异",
    "business_model": "商业模式差异",
    "business": "商业模式差异",
    "monetization": "商业模式（变现）",
    "revenue": "收入结构",
    "pricing": "定价策略",
    "ux": "用户体验",
    "usability": "用户体验",
    "experience": "用户体验",
    "features": "核心功能对比",
    "feature": "核心功能对比",
    "technology": "技术能力",
    "architecture": "技术架构",
    "tech stack": "技术能力",
    "risks": "政策监管与风险",
    "risk": "政策监管与风险",
    "compliance": "合规风险",
    "regulation": "政策监管",
    "policy": "政策监管",
    "market share": "市场竞争（份额）",
    "market": "市场竞争",
    "competition": "竞争格局",
    "competitive": "竞争格局",
    "brand": "品牌口碑",
    "reputation": "品牌口碑",
    "operations": "运营策略",
    "marketing": "营销策略",
    "acquisition": "获客策略",
    "channel": "渠道策略",
}


def normalize_dimension(dim: str) -> str:
    """Map an English/foreign dimension name to the canonical Chinese one."""
    key = (dim or "").strip().lower()
    if not key:
        return dim
    if key in _DIMENSION_ZH_MAP:
        return _DIMENSION_ZH_MAP[key]
    # Compound names ("competitive landscape", "user growth trends", ...)
    for eng, zh in _DIMENSION_ZH_MAP.items():
        if eng in key:
            return zh
    return dim


class PlannerAgent(BaseAgent[PlannerInput, PlannerOutput]):
    """Planner Agent — uses LLM to generate dynamic research plans.

    Workflow:
      1. Build prompt from user input
      2. Call LLM with structured output schema
      3. Map LLM output → ResearchPlan with individual ResearchTasks
      4. Fallback to mock plan if LLM unavailable or fails
    """

    @property
    def agent_name(self) -> str:
        return "planner"

    @property
    def phase(self) -> Phase:
        return Phase.PLANNING

    async def arun(self, ctx: AgentContext, input_data: PlannerInput) -> AgentResult:
        """Generate a ResearchPlan using LLM, with mock fallback."""

        # ── Step 1: Try LLM ──
        llm_plan = await self._try_llm_plan(input_data)

        if llm_plan:
            plan = self._build_research_plan(input_data, llm_plan)
        else:
            # ── Step 2: Fallback to mock ──
            plan = self._mock_plan(input_data)

        output = PlannerOutput(
            research_plan=plan,
            phase_record={
                "phase": Phase.PLANNED.value,
                "duration_ms": 0,
                "status": "completed",
                "llm_generated": llm_plan is not None,
            },
        )
        return AgentResult(success=True, output=output)

    # ── LLM Path ──

    async def _try_llm_plan(
        self,
        input_data: PlannerInput,
    ) -> LLMResearchPlanOutput | None:
        """Attempt to generate a plan via LLM. Returns None on failure."""
        user_prompt = build_user_prompt(
            our_company=input_data.our_company,
            competitor_company=input_data.competitor_company,
            product=input_data.product,
            objective=input_data.objective,
            optional_context=input_data.optional_context,
        )

        try:
            llm_timeout = input_data.llm_timeout_seconds
            gen_kwargs: dict = {
                "system_prompt": SYSTEM_PROMPT,
                "user_prompt": user_prompt,
                "response_model": LLMResearchPlanOutput,
                "temperature": 0.7,
            }
            if llm_timeout is not None:
                gen_kwargs["timeout"] = llm_timeout
            result = await llm_client.generate(**gen_kwargs)

            parsed = result.parsed
            if parsed and parsed.analysis_goal and len(parsed.research_dimensions) >= 2:
                return parsed

            return None
        except Exception:
            return None

    # ── Build ResearchPlan from LLM output ──

    def _build_research_plan(
        self,
        input_data: PlannerInput,
        llm_plan: LLMResearchPlanOutput,
    ) -> ResearchPlan:
        """Map LLM structured output → ResearchPlan with individual ResearchTasks."""
        dimensions = [normalize_dimension(d) for d in llm_plan.research_dimensions]
        base_keywords = [
            input_data.our_company,
            input_data.competitor_company,
            input_data.product,
            f"{input_data.our_company} {input_data.product}",
            f"{input_data.competitor_company} {input_data.product}",
        ]
        # Add LLM-generated keywords
        all_keywords = base_keywords + [
            kw for kw in llm_plan.search_keywords
            if kw not in base_keywords
        ]

        # Create ResearchTasks for each source type
        tasks: list[ResearchTask] = []
        sources_used: set[str] = set()

        for i, source_type in enumerate(_SOURCE_TYPES):
            priority = max(1, min(5, llm_plan.priority + _SOURCE_PRIORITY_BOOST.get(source_type, 0)))
            suffix = _SOURCE_KEYWORD_SUFFIX.get(source_type, "")

            # Pick the most relevant keywords for this source
            task_keywords = [f"{kw}{suffix}" for kw in all_keywords[:3]]

            # Add dimension-specific keywords from the LLM output
            if dimensions and i < len(dimensions):
                dim = dimensions[i]
                task_keywords.append(f"{input_data.competitor_company} {dim}")

            task = ResearchTask(
                task_id=f"task_{source_type}_{i:03d}",
                source_type=source_type,
                keywords=task_keywords,
                priority=priority,
                dependencies=[],
            )
            tasks.append(task)
            sources_used.add(source_type)

        # Build the ResearchPlan
        plan = ResearchPlan(
            objective=llm_plan.analysis_goal[:200],
            analysis_scope=dimensions,
            research_tasks=tasks,
            required_sources=sorted(sources_used),
            workflow=list(_WORKFLOW_STEPS),
            estimated_complexity=llm_plan.estimated_complexity,
        )
        return plan

    # ── Mock Fallback ──

    @staticmethod
    def _mock_plan(input_data: PlannerInput) -> ResearchPlan:
        """Fallback: return a standard research plan when LLM unavailable."""
        return ResearchPlan(
            objective=input_data.objective,
            analysis_scope=[
                "产品定位与品牌",
                "用户画像与行为变化",
                "核心功能对比",
                "商业模式差异",
                "增长策略与市场",
            ],
            research_tasks=[
                ResearchTask(
                    task_id="task_web_001",
                    source_type="web",
                    keywords=[input_data.our_company, input_data.competitor_company, input_data.product],
                    priority=5,
                    dependencies=[],
                ),
                ResearchTask(
                    task_id="task_as_001",
                    source_type="app_store",
                    keywords=[input_data.our_company, input_data.product],
                    priority=3,
                    dependencies=[],
                ),
                ResearchTask(
                    task_id="task_social_001",
                    source_type="social",
                    keywords=[input_data.our_company, input_data.competitor_company],
                    priority=3,
                    dependencies=[],
                ),
                ResearchTask(
                    task_id="task_ai_001",
                    source_type="ai_search",
                    keywords=[f"{input_data.our_company} {input_data.competitor_company} {input_data.product} 竞品分析"],
                    priority=4,
                    dependencies=[],
                ),
            ],
            required_sources=["web", "app_store", "social", "ai_search"],
            workflow=list(_WORKFLOW_STEPS),
            estimated_complexity="moderate",
        )
