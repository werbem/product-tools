"""Source Selection Engine — configurable dimension→source mapping.

Independent module. Not coupled to any Agent.
Replaces hardcoded source selection in ResearchAgent.

Rules map analysis dimension keywords → specific source types.
Config is a plain dict, easily updated or replaced by LLM.

Future: LLM can suggest additional sources via `build_with_llm_override()`.

Architecture:
  ResearchPlan → SourceSelectionEngine → SourceExecutionPlan
      ↓
  SourceRouter.execute_plan()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from app.infrastructure.tools.research_source import SourceType


# ═══════════════════════════════════════════════════
#  Source Selection Rules (configurable)
# ═══════════════════════════════════════════════════

SELECTION_RULES: dict[str, list[str]] = {
    # ── 用户体验 → AppStore, GooglePlay, Community ──
    "用户体验": [SourceType.APP_STORE, SourceType.SOCIAL],
    "用户":     [SourceType.APP_STORE, SourceType.SOCIAL, SourceType.WEB],
    "界面":     [SourceType.APP_STORE, SourceType.WEB],
    "交互":     [SourceType.APP_STORE, SourceType.WEB],
    "评价":     [SourceType.APP_STORE, SourceType.SOCIAL],
    "评分":     [SourceType.APP_STORE, SourceType.SOCIAL],

    # ── 产品功能 → OfficialWebsite, Tavily ──
    "功能":     [SourceType.OFFICIAL, SourceType.WEB],
    "features": [SourceType.OFFICIAL, SourceType.WEB],
    "产品":     [SourceType.OFFICIAL, SourceType.WEB],

    # ── 商业模式 → OfficialWebsite, News ──
    "商业":     [SourceType.OFFICIAL, SourceType.NEWS],
    "盈利":     [SourceType.OFFICIAL, SourceType.NEWS],
    "定价":     [SourceType.OFFICIAL, SourceType.WEB],
    "付费":     [SourceType.APP_STORE, SourceType.WEB],
    "收入":     [SourceType.WEB, SourceType.NEWS],

    # ── 增长策略 → News, Community ──
    "增长":     [SourceType.NEWS, SourceType.SOCIAL],
    "运营":     [SourceType.NEWS, SourceType.SOCIAL],
    "营销":     [SourceType.NEWS, SourceType.SOCIAL, SourceType.WEB],
    "获客":     [SourceType.NEWS, SourceType.SOCIAL],
    "策略":     [SourceType.NEWS, SourceType.WEB],

    # ── 技术能力 → GitHub, OfficialWebsite ──
    "技术":     [SourceType.DEVELOPER, SourceType.OFFICIAL, SourceType.WEB],
    "架构":     [SourceType.DEVELOPER, SourceType.OFFICIAL],
    "ai":       [SourceType.WEB, SourceType.DEVELOPER],
    "开发":     [SourceType.DEVELOPER, SourceType.WEB],
    "开源":     [SourceType.DEVELOPER, SourceType.WEB],

    # ── 市场 → News, OfficialWebsite ──
    "市场":     [SourceType.NEWS, SourceType.WEB, SourceType.OFFICIAL],
    "竞争":     [SourceType.NEWS, SourceType.WEB],
    "竞品":     [SourceType.NEWS, SourceType.WEB, SourceType.APP_STORE],

    # ── 定位 → OfficialWebsite, News ──
    "定位":     [SourceType.OFFICIAL, SourceType.WEB, SourceType.NEWS],
    "品牌":     [SourceType.WEB, SourceType.SOCIAL, SourceType.NEWS],

    # ── 风险 → News, OfficialWebsite ──
    "风险":     [SourceType.WEB, SourceType.NEWS],
    "合规":     [SourceType.WEB, SourceType.NEWS],
    "监管":     [SourceType.WEB, SourceType.NEWS],

    # ═══════════════════════════════════════════════════
    #  English dimension aliases (Planner/LLM often returns
    #  English dimension names such as positioning/users/growth)
    # ═══════════════════════════════════════════════════
    "user growth":  [SourceType.NEWS, SourceType.WEB, SourceType.SOCIAL],
    "user_growth":  [SourceType.NEWS, SourceType.WEB, SourceType.SOCIAL],
    "usergrowth":   [SourceType.NEWS, SourceType.WEB, SourceType.SOCIAL],
    "positioning":  [SourceType.OFFICIAL, SourceType.WEB, SourceType.NEWS],
    "users":        [SourceType.APP_STORE, SourceType.SOCIAL, SourceType.WEB],
    "user":         [SourceType.APP_STORE, SourceType.SOCIAL, SourceType.WEB],
    "growth":       [SourceType.NEWS, SourceType.WEB, SourceType.SOCIAL],
    "business model": [SourceType.OFFICIAL, SourceType.NEWS, SourceType.WEB],
    "business_model": [SourceType.OFFICIAL, SourceType.NEWS, SourceType.WEB],
    "business":     [SourceType.OFFICIAL, SourceType.NEWS, SourceType.WEB],
    "monetization": [SourceType.OFFICIAL, SourceType.NEWS, SourceType.WEB],
    "revenue":      [SourceType.WEB, SourceType.NEWS],
    "pricing":      [SourceType.OFFICIAL, SourceType.WEB],
    "ux":           [SourceType.APP_STORE, SourceType.SOCIAL, SourceType.WEB],
    "usability":    [SourceType.APP_STORE, SourceType.SOCIAL, SourceType.WEB],
    "experience":   [SourceType.APP_STORE, SourceType.SOCIAL, SourceType.WEB],
    "technology":   [SourceType.DEVELOPER, SourceType.OFFICIAL, SourceType.WEB],
    "architecture": [SourceType.DEVELOPER, SourceType.OFFICIAL],
    "tech stack":   [SourceType.DEVELOPER, SourceType.WEB],
    "risks":        [SourceType.WEB, SourceType.NEWS],
    "risk":         [SourceType.WEB, SourceType.NEWS],
    "compliance":   [SourceType.WEB, SourceType.NEWS],
    "regulation":   [SourceType.WEB, SourceType.NEWS],
    "policy":       [SourceType.WEB, SourceType.NEWS],
    "market share": [SourceType.NEWS, SourceType.WEB, SourceType.OFFICIAL],
    "market":       [SourceType.NEWS, SourceType.WEB, SourceType.OFFICIAL],
    "competition":  [SourceType.NEWS, SourceType.WEB],
    "competitive":  [SourceType.NEWS, SourceType.WEB],
    "brand":        [SourceType.WEB, SourceType.SOCIAL, SourceType.NEWS],
    "reputation":   [SourceType.WEB, SourceType.SOCIAL, SourceType.NEWS],
    "operations":   [SourceType.NEWS, SourceType.SOCIAL, SourceType.WEB],
    "marketing":    [SourceType.NEWS, SourceType.SOCIAL, SourceType.WEB],
    "acquisition":  [SourceType.NEWS, SourceType.SOCIAL],
    "channel":      [SourceType.NEWS, SourceType.SOCIAL, SourceType.WEB],
}

# Default when no dimension matches
_DEFAULT_SOURCES = [SourceType.WEB]


# ═══════════════════════════════════════════════════
#  Execution Plan
# ═══════════════════════════════════════════════════

@dataclass
class SelectionTask:
    """A single research task in the execution plan."""
    dimension: str
    sources: list[str]      # source_type strings
    keywords: list[str]
    priority: int = 3       # 1 (low) to 5 (high)


@dataclass
class ResearchExecutionPlan:
    """Complete source execution plan generated from ResearchPlan."""
    objective: str = ""
    dimensions: list[str] = field(default_factory=list)
    tasks: list[SelectionTask] = field(default_factory=list)
    all_source_types: list[str] = field(default_factory=list)

    @property
    def total_sources(self) -> int:
        return len(self.all_source_types)

    @property
    def total_tasks(self) -> int:
        return len(self.tasks)


# ═══════════════════════════════════════════════════
#  Source Selection Engine
# ═══════════════════════════════════════════════════

class SourceSelectionEngine:
    """Maps research dimensions → source types using configurable rules.

    Independent of any Agent. Rules can be updated at runtime.
    Supports LLM override for future dynamic selection.
    """

    def __init__(self, rules: Optional[dict] = None):
        self._rules = dict(rules) if rules else dict(SELECTION_RULES)

    @property
    def rules(self) -> dict:
        return dict(self._rules)

    def update_rules(self, new_rules: dict) -> None:
        """Merge new rules. Existing keys are overwritten."""
        self._rules.update(new_rules)

    def build_plan(
        self,
        dimensions: list[str],
        keywords: list[str],
        objective: str = "",
    ) -> ResearchExecutionPlan:
        """Build a ResearchExecutionPlan from analysis dimensions.

        Args:
            dimensions: Analysis dimension names from Planner
            keywords: Search keywords from Planner
            objective: Analysis objective description

        Returns:
            ResearchExecutionPlan with per-dimension source assignments
        """
        if not dimensions:
            return ResearchExecutionPlan(
                objective=objective,
                dimensions=[],
                tasks=[SelectionTask(
                    dimension="default",
                    sources=list(_DEFAULT_SOURCES),
                    keywords=keywords,
                    priority=5,
                )],
                all_source_types=list(_DEFAULT_SOURCES),
            )

        tasks: list[SelectionTask] = []
        all_sources: set[str] = set()

        for dim in dimensions:
            sources = self._match_sources(dim)
            all_sources.update(sources)

            tasks.append(SelectionTask(
                dimension=dim,
                sources=sources,
                keywords=self._pick_keywords(dim, keywords),
                priority=self._infer_priority(dim),
            ))

        return ResearchExecutionPlan(
            objective=objective,
            dimensions=list(dimensions),
            tasks=tasks,
            all_source_types=sorted(all_sources),
        )

    def build_with_llm_override(
        self,
        dimensions: list[str],
        keywords: list[str],
        objective: str,
        llm_suggestions: Optional[dict[str, list[str]]] = None,
    ) -> ResearchExecutionPlan:
        """Build a plan with optional LLM source suggestions.

        Future: an LLM can review dimensions and suggest per-dimension
        source overrides that are merged with the configured rules.

        Args:
            llm_suggestions: dict of dimension → [source_types]
        """
        plan = self.build_plan(dimensions, keywords, objective)

        if llm_suggestions:
            for dim, suggested_sources in llm_suggestions.items():
                for task in plan.tasks:
                    if task.dimension == dim:
                        merged = set(task.sources) | set(suggested_sources)
                        task.sources = sorted(merged)

        return plan

    # ── Internals ──

    def _match_sources(self, dimension: str) -> list[str]:
        """Match a dimension string to source types using rules."""
        dim_lower = dimension.lower()
        for keyword, sources in self._rules.items():
            if keyword.lower() in dim_lower:
                return list(sources)
        return list(_DEFAULT_SOURCES)

    @staticmethod
    def _pick_keywords(dimension: str, all_keywords: list[str]) -> list[str]:
        """Pick relevant keywords for a dimension."""
        if not all_keywords:
            return [dimension]
        # Return first 3 keywords
        return all_keywords[:3]

    @staticmethod
    def _infer_priority(dimension: str) -> int:
        """Infer priority from dimension name. Higher = more urgent."""
        dim_lower = dimension.lower()
        high_priority = ["风险", "安全", "合规", "增长"]
        for kw in high_priority:
            if kw in dim_lower:
                return 5
        return 3


# ── Singleton ──

source_selection = SourceSelectionEngine()
