"""External MCP schemas for Competitive Intelligence MCP.

These models are deliberately independent of the internal LangGraph DTOs.
Adapters in ``app.interfaces.mcp.adapters`` translate between these schemas
and ``app.infrastructure.workflow.state.WorkflowState``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


MCP_SCHEMA_VERSION = "1.0"
MCPStatus = Literal["completed", "partial", "no_data", "failed"]
MCPOutputLevel = Literal["brief", "standard", "deep"]


class CompanyContext(BaseModel):
    """Companies and product involved in a competitive analysis."""

    our_company: str = Field(..., min_length=1)
    competitor_company: str = Field(..., min_length=1)
    product: str = Field(..., min_length=1)


class CollectCompetitorIntelligenceInput(BaseModel):
    """Input for the collect_competitor_intelligence tool."""

    our_company: str = Field(..., min_length=1)
    competitor_company: str = Field(..., min_length=1)
    product: str = Field(..., min_length=1)
    objective: str = Field(default="product_improvement", min_length=1)
    dimensions: list[str] = Field(default_factory=list)
    source_types: list[str] = Field(default_factory=list)
    max_evidence: int = Field(default=50, ge=1, le=100)


class MCPEvidenceSource(BaseModel):
    """Source metadata attached to one collected evidence item."""

    name: str = ""
    type: str = ""
    url: str = ""
    published_at: str = ""


class MCPEvidenceQuality(BaseModel):
    """Structured quality score for one evidence item."""

    authority: float = 0.0
    freshness: float = 0.0
    relevance: float = 0.0
    reliability: float = 0.0
    overall: float = 0.0


class MCPEvidenceItem(BaseModel):
    """One standardized competitive intelligence evidence item."""

    finding_id: str = Field(..., min_length=1)
    dimension: str = ""
    finding: str = ""
    source: MCPEvidenceSource = Field(default_factory=MCPEvidenceSource)
    confidence: str = "medium"
    quality: MCPEvidenceQuality | None = None
    created_at: str = ""


class MCPCoverage(BaseModel):
    """Collection coverage summary."""

    total_evidence: int = 0
    returned_evidence: int = 0
    sources_attempted: int = 0
    sources_succeeded: int = 0
    by_dimension: dict[str, int] = Field(default_factory=dict)


class CollectCompetitorIntelligenceOutput(BaseModel):
    """Output for the collect_competitor_intelligence tool."""

    schema_version: str = MCP_SCHEMA_VERSION
    collection_id: str
    status: MCPStatus = "completed"
    error_code: str | None = None
    message: str = ""
    objective: str = "product_improvement"
    companies: CompanyContext
    dimensions: list[str] = Field(default_factory=list)
    evidenceItem: list[MCPEvidenceItem] = Field(default_factory=list)
    coverage: MCPCoverage = Field(default_factory=MCPCoverage)
    warnings: list[str] = Field(default_factory=list)


class AnalyzeCompetitionInput(BaseModel):
    """Input for the analyze_competition tool.

    ``intelligence`` is optional. When omitted, the workflow must collect
    evidence internally before running analysis.
    """

    our_company: str = Field(..., min_length=1)
    competitor_company: str = Field(..., min_length=1)
    product: str = Field(..., min_length=1)
    objective: str = Field(default="product_improvement", min_length=1)
    intelligence: dict[str, Any] | None = None
    output_level: MCPOutputLevel = "standard"


class MCPReportMetadata(BaseModel):
    """Report metadata for analyze_competition output."""

    word_count: int = 0
    section_count: int = 0
    confidence: str | None = None


class AnalyzeCompetitionOutput(BaseModel):
    """Output for the analyze_competition tool."""

    schema_version: str = MCP_SCHEMA_VERSION
    summary: str = ""
    status: MCPStatus = "completed"
    error_code: str | None = None
    message: str = ""
    comparison: dict[str, Any] = Field(default_factory=dict)
    advantages: list[dict[str, Any]] = Field(default_factory=list)
    gaps: list[dict[str, Any]] = Field(default_factory=list)
    recommendations: list[dict[str, Any]] = Field(default_factory=list)
    report_markdown: str = ""
    metadata: MCPReportMetadata = Field(default_factory=MCPReportMetadata)
