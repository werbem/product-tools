"""Agent I/O DTOs — defines the contract for every Agent node."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


# ── User Input ──

class UserInputDTO(BaseModel):
    our_company: str
    competitor_company: str
    product: str
    objective: str
    scene: Optional[str] = None
    optional: Optional[dict] = None

    @field_validator("scene", mode="before")
    @classmethod
    def strip_scene(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class ValidatedInputDTO(BaseModel):
    is_valid: bool
    clean_values: dict[str, Any]
    issues: list[dict] = Field(default_factory=list)


# ── Gate Agent I/O ──

class GateInput(BaseModel):
    user_input: UserInputDTO


class GateOutput(BaseModel):
    validated_input: ValidatedInputDTO
    current_phase: str


# ── Planner Agent I/O ──

class ResearchTask(BaseModel):
    task_id: str
    source_type: str
    keywords: list[str]
    priority: int = Field(default=3, ge=1, le=5)
    dependencies: list[str] = Field(default_factory=list)


class ResearchPlan(BaseModel):
    objective: str
    analysis_scope: list[str]
    research_tasks: list[ResearchTask]
    required_sources: list[str] = Field(default_factory=list)
    workflow: list[str] = Field(default_factory=list)
    estimated_complexity: str = "moderate"


class PlannerInput(BaseModel):
    our_company: str
    competitor_company: str
    product: str
    objective: str
    optional_context: Optional[str] = None
    llm_timeout_seconds: Optional[float] = None


class PlannerOutput(BaseModel):
    research_plan: ResearchPlan
    phase_record: dict


# ── Research Agent I/O ──

class EvidenceItemDTO(BaseModel):
    id: Optional[str] = None
    title: str = ""
    source: str
    source_type: str = "web"
    url: str = ""
    date: str = ""
    content: str
    confidence: str = "estimated"
    category: str = ""
    extracted_at: Optional[datetime] = None
    raw_data: Optional[dict] = None
    quality_score: Optional[dict] = None


class CompanyInfoDTO(BaseModel):
    name: str = ""
    description: str = ""
    positioning: str = ""
    business_model: str = ""
    market_focus: str = ""
    funding_stage: str = ""
    data_quality: str = "no_data"


class ProductInfoDTO(BaseModel):
    name: str = ""
    category: str = ""
    description: str = ""
    key_features: list[str] = Field(default_factory=list)
    target_users: str = ""
    platforms: list[str] = Field(default_factory=list)
    pricing: str = ""
    data_quality: str = "no_data"


class EvidenceBundleDTO(BaseModel):
    our_company: CompanyInfoDTO = Field(default_factory=CompanyInfoDTO)
    competitor_company: CompanyInfoDTO = Field(default_factory=CompanyInfoDTO)
    our_product: ProductInfoDTO = Field(default_factory=ProductInfoDTO)
    competitor_product: ProductInfoDTO = Field(default_factory=ProductInfoDTO)
    evidence_items: list[EvidenceItemDTO] = Field(default_factory=list)
    news: list[dict] = Field(default_factory=list)
    reviews: list[dict] = Field(default_factory=list)
    market: list[dict] = Field(default_factory=list)
    sources_used: list = Field(default_factory=list)
    references: list[dict] = Field(default_factory=list)
    quality_score: dict = Field(default_factory=lambda: {
        "overall": 0, "coverage": 0, "freshness": 0,
    })


class QualityReport(BaseModel):
    sources_attempted: int = 0
    sources_succeeded: int = 0
    total_evidence_items: int = 0
    coverage_by_dimension: dict[str, float] = Field(default_factory=dict)
    avg_confidence: float = 0.0
    fallback_used: bool = False
    missing_data_warnings: list[str] = Field(default_factory=list)
    # Research timeout / raw fallback diagnostics (Step 34)
    research_timeout: bool = False
    evidence_fallback: Optional[str] = None  # e.g. "raw_search"
    raw_items_converted: int = 0
    # Step 42: age window diagnostics
    filtered_expired_count: int = 0
    undated_kept_count: int = 0
    undated_dropped_count: int = 0
    evidence_cutoff_date: str = ""
    date_enrichment_attempted: int = 0
    date_enrichment_succeeded: int = 0


class ResearchInput(BaseModel):
    research_plan: Optional[dict] = None
    our_company: str = ""
    competitor_company: str = ""
    product: str = ""
    time_budget_seconds: float = 300.0
    max_source_types: int = 3
    max_results_per_source: int = 5
    skip_evidence_evaluation: bool = False
    max_evidence_items: Optional[int] = None
    max_evaluated_items: Optional[int] = None
    # Step 42
    evidence_max_age_months: int = 48
    max_undated_evidence_items: int = 5
    enable_lightweight_date_enrichment: bool = True
    date_enrichment_timeout_s: float = 2.5
    date_enrichment_max_urls: int = 8


class ResearchOutput(BaseModel):
    evidence_bundle: EvidenceBundleDTO
    quality_report: QualityReport


# ── Compare Agent I/O ──

class FeatureItem(BaseModel):
    category: str
    feature_name: str
    our_coverage: str = "unknown"
    competitor_coverage: str = "unknown"
    differentiator: bool = False
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)


class GapItem(BaseModel):
    dimension: str
    description: str
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)
    impact: str = "medium"
    evidence_temporal_level: str = "unknown"


class GapAnalysis(BaseModel):
    positioning: dict = Field(default_factory=dict)
    features: dict = Field(default_factory=lambda: {"feature_matrix": [], "unique_our_features": [], "unique_competitor_features": []})
    users: dict = Field(default_factory=dict)
    business: dict = Field(default_factory=dict)
    growth: dict = Field(default_factory=dict)
    ai_capability: dict = Field(default_factory=dict)
    gaps: dict = Field(default_factory=lambda: {"competitive_advantages": [], "competitive_disadvantages": [], "capability_gaps": []})
    evidence_references: list[str] = Field(default_factory=list)




# ── Insight Agent I/O ──

class ProductInsight(BaseModel):
    title: str
    type: str  # fact | observation | hypothesis
    description: str
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)
    confidence: str = "medium"  # high | medium | low
    impact: str = "medium"  # high | medium | low
    dimension: str = ""
    evidence_temporal_level: str = "unknown"


class InsightInput(BaseModel):
    evidence_clusters: Optional[list[dict]] = None
    gap_analysis: Optional[dict] = None
    flat_evidence_items: Optional[list] = None
    our_company: str
    competitor_company: str
    product: str
    objective: str = ""
    llm_timeout_seconds: Optional[float] = None


class InsightOutput(BaseModel):
    insights: list[ProductInsight] = Field(default_factory=list)
    fact_count: int = 0
    observation_count: int = 0
    hypothesis_count: int = 0
    summary: str = ""

class CompareInput(BaseModel):
    evidence_bundle: Optional[dict] = Field(default_factory=dict)
    evidence_clusters: Optional[list[dict]] = None
    analysis_scope: list[str] = Field(default_factory=list)
    objective: str = ""
    our_company: str = ""
    competitor_company: str = ""
    product: str = ""
    llm_timeout_seconds: Optional[float] = None
    compact: bool = True
    research_incomplete: bool = False


class CompareOutput(BaseModel):
    gap_analysis: GapAnalysis
    dimensions_analyzed: list[str] = Field(default_factory=list)
    dimensions_skipped: list[str] = Field(default_factory=list)
    evidence_references_count: int = 0


# ── Strategy Agent I/O ──

class SWOTItem(BaseModel):
    item: str
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class SWOT(BaseModel):
    strengths: list[SWOTItem] = Field(default_factory=list)
    weaknesses: list[SWOTItem] = Field(default_factory=list)
    opportunities: list[SWOTItem] = Field(default_factory=list)
    threats: list[SWOTItem] = Field(default_factory=list)


class OpportunityItem(BaseModel):
    title: str
    description: str
    impact: str = "medium"
    effort: str = "medium"
    alignment_with_objective: str = Field(default="medium")

    @field_validator('alignment_with_objective', mode='before')
    @classmethod
    def _coerce_awo(cls, v):
        if isinstance(v, int):
            return str(v)
        return v
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: str = "medium"


class RiskItem(BaseModel):
    title: str
    description: str
    probability: str = "medium"
    impact: str = "medium"
    mitigation: str = ""
    evidence_refs: list[str] = Field(default_factory=list)


class RecommendationItem(BaseModel):
    expected_value: str = ""
    action: str
    rationale: str
    priority: str = "p2"
    timeline: str = "short_term"
    evidence_refs: list[str] = Field(default_factory=list)
    cluster_refs: list[str] = Field(default_factory=list)
    kpi: Optional[str] = None
    evidence_temporal_level: str = "unknown"


class RoadmapPhase(BaseModel):
    phase: str
    duration: str
    initiatives: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)


class StrategicInsights(BaseModel):
    swot: SWOT = Field(default_factory=SWOT)
    opportunities: list[OpportunityItem] = Field(default_factory=list)
    risks: list[RiskItem] = Field(default_factory=list)
    recommendations: list[RecommendationItem] = Field(default_factory=list)
    roadmap: dict = Field(default_factory=lambda: {"phases": []})
    confidence_labels: dict[str, str] = Field(default_factory=dict)


class StrategyInput(BaseModel):
    gap_analysis: dict = Field(default_factory=dict)
    evidence_bundle: dict = Field(default_factory=dict)
    insights: Optional[list[dict]] = None
    objective: str = ""
    product: str = ""
    our_company: str = ""
    competitor_company: str = ""
    llm_timeout_seconds: Optional[float] = None
    compact: bool = True
    research_incomplete: bool = False
    memory_notes_context: Optional[str] = None


class StrategyOutput(BaseModel):
    strategic_insights: StrategicInsights
    confidence_summary: dict = Field(default_factory=lambda: {
        "overall": "medium", "weaknesses": [], "data_gaps": [],
    })


# ── Report Agent I/O ──

class ReportSectionDTO(BaseModel):
    title: str
    content: str
    order: int
    word_count: int = 0


class ReportFormatsDTO(BaseModel):
    markdown: Optional[str] = None
    html: Optional[str] = None
    docx_url: Optional[str] = None


class ReportDocument(BaseModel):
    formats: ReportFormatsDTO = Field(default_factory=ReportFormatsDTO)
    sections: list[ReportSectionDTO] = Field(default_factory=list)
    metadata: dict = Field(default_factory=lambda: {
        "total_word_count": 0,
        "generated_at": None,
        "sources_count": 0,
        "template_used": "v1",
        "llm_prompt_tokens": 0,
        "llm_completion_tokens": 0,
    })


class ReportInput(BaseModel):
    evidence_bundle: dict = Field(default_factory=dict)
    gap_analysis: dict = Field(default_factory=dict)
    strategic_insights: dict = Field(default_factory=dict)
    template_version: str = "v1"
    output_formats: list[str] = Field(default_factory=lambda: ["markdown", "docx"])
    objective: str = ""
    product: str = ""
    our_company: str = ""
    competitor_company: str = ""
    llm_timeout_seconds: Optional[float] = None
    segment_timeout_seconds: Optional[float] = None
    fast_mode: bool = False
    compact_report: bool = False
    memory_notes_context: Optional[str] = None


class ReportOutput(BaseModel):
    report_document: ReportDocument


# ── Review Agent I/O ──

class ReviewIssue(BaseModel):
    severity: str = "minor"
    category: str = ""
    section: str = ""
    description: str = ""
    suggestion: str = ""


class ReviewResult(BaseModel):
    passed: bool = False
    score: int = Field(default=0, ge=0, le=100)
    checks: dict = Field(default_factory=lambda: {
        "completeness": False,
        "logic": False,
        "sources": False,
        "duplication": False,
        "format": False,
        "neutrality": False,
        "actionability": False,
    })
    issues: list[ReviewIssue] = Field(default_factory=list)
    revision_suggestions: list[dict] = Field(default_factory=list)
    passed_for_output: bool = False
    deletion_suggestions: list[dict] = Field(default_factory=list)
    high_issue_count: int = 0
    fact_audit_passed: bool = False


class ReviewInput(BaseModel):
    report_document: dict = Field(default_factory=dict)
    evidence_bundle: dict = Field(default_factory=dict)
    objective: str = ""
    template_version: str = "v1"
    llm_timeout_seconds: Optional[float] = None


class ReviewOutput(BaseModel):
    review_result: ReviewResult
    passed_for_output: bool = False
    score: int = 0
    check_summary: dict = Field(default_factory=dict)
    issue_count: dict = Field(default_factory=lambda: {
        "critical": 0, "major": 0, "minor": 0, "suggestion": 0,
    })
