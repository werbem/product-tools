"""Translate internal workflow results into MCP output schemas."""

from __future__ import annotations

from collections import Counter
from typing import Any

from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionOutput,
    CollectCompetitorIntelligenceOutput,
    CompanyContext,
    MCPCoverage,
    MCPReportMetadata,
)
from app.interfaces.mcp.adapters.evidence_standardizer import EvidenceStandardizer


class CollectOutputAdapter:
    """Build collect_competitor_intelligence output from internal state."""

    def from_internal_state(
        self,
        internal_state: dict[str, Any],
        max_evidence: int = 50,
    ) -> CollectCompetitorIntelligenceOutput:
        evidence_bundle = internal_state.get("evidence_bundle") or {}
        raw_items = evidence_bundle.get("evidence_items", [])
        items = EvidenceStandardizer().standardize(raw_items)
        items = self._rank_and_limit(items, max_evidence)

        quality = internal_state.get("quality_report") or {}
        meta = internal_state.get("collection_meta") or {}
        phase = internal_state.get("current_phase", "")
        errors = internal_state.get("errors") or []

        warnings = [str(w) for w in quality.get("missing_data_warnings", [])]
        warnings.extend(str(w) for w in meta.get("warnings", []))

        sources_attempted = int(meta.get("sources_attempted", quality.get("sources_attempted", 0)) or 0)
        sources_succeeded = int(meta.get("sources_succeeded", quality.get("sources_succeeded", 0)) or 0)

        dimension_counts = Counter(
            item.dimension or "other" for item in items
        )

        if phase in {"failed", "validation_failed", "collection_failed"} or errors:
            status = "failed"
        elif not items:
            status = "no_data"
        elif warnings or sources_succeeded < sources_attempted:
            status = "partial"
        else:
            status = "completed"

        validated = internal_state.get("validated_input") or {}
        user_input = internal_state.get("user_input") or {}
        research_plan = internal_state.get("research_plan") or {}

        return CollectCompetitorIntelligenceOutput(
            collection_id=internal_state.get("task_id", ""),
            status=status,
            objective=validated.get("objective") or user_input.get("objective", "product_improvement"),
            companies=CompanyContext(
                our_company=validated.get("our_company") or user_input.get("our_company", ""),
                competitor_company=validated.get("competitor_company") or user_input.get("competitor_company", ""),
                product=validated.get("product") or user_input.get("product", ""),
            ),
            dimensions=research_plan.get("analysis_scope", []),
            evidenceItem=items,
            coverage=MCPCoverage(
                total_evidence=len(raw_items),
                returned_evidence=len(items),
                sources_attempted=sources_attempted,
                sources_succeeded=sources_succeeded,
                by_dimension=dict(dimension_counts),
            ),
            warnings=warnings,
        )

    @staticmethod
    def _rank_and_limit(items: list, max_evidence: int) -> list:
        confidence_order = {"high": 0, "medium": 1, "low": 2, "estimated": 3}

        def sort_key(item):
            confidence = confidence_order.get(item.confidence, 3)
            quality = item.quality
            overall = quality.overall if quality else 0.0
            relevance = quality.relevance if quality else 0.0
            return (confidence, -overall, -relevance)

        return sorted(items, key=sort_key)[:max_evidence]


class AnalyzeOutputAdapter:
    """Build analyze_competition output from internal state."""

    def from_internal_state(
        self,
        internal_state: dict[str, Any],
        output_level: str = "standard",
    ) -> AnalyzeCompetitionOutput:
        phase = internal_state.get("current_phase", "")
        errors = internal_state.get("errors") or []
        evidence_bundle = internal_state.get("evidence_bundle") or {}
        evidence_items = evidence_bundle.get("evidence_items", [])
        gap_analysis = internal_state.get("gap_analysis") or {}
        strategic_insights = internal_state.get("strategic_insights") or {}
        review = internal_state.get("review_result") or {}
        report_document = internal_state.get("report_document") or {}
        insights = internal_state.get("insights") or {}

        markdown = (report_document.get("formats") or {}).get("markdown", "") or ""
        summary = insights.get("summary", "") if isinstance(insights, dict) else ""
        if not summary and markdown:
            summary = markdown[:500]

        status = self._resolve_status(
            phase=phase,
            errors=errors,
            evidence_count=len(evidence_items),
            review=review,
            has_report=bool(markdown),
        )

        gap_sections = gap_analysis.get("gaps", {}) or {}
        sections = report_document.get("sections", [])
        report_metadata = report_document.get("metadata") or {}
        word_count = int(
            report_metadata.get("total_word_count")
            or len(markdown.replace("\n", ""))
            or 0
        )
        section_count = len(sections)
        confidence = None
        if output_level == "deep":
            confidence_labels = strategic_insights.get("confidence_labels") or {}
            confidence = confidence_labels.get("overall")

        comparison = {
            "positioning": gap_analysis.get("positioning", {}),
            "feature_matrix": (gap_analysis.get("features") or {}).get("feature_matrix", []),
        }
        advantages = gap_sections.get("competitive_advantages", [])
        gaps = gap_sections.get("capability_gaps", [])
        recommendations = strategic_insights.get("recommendations", [])

        if output_level == "brief":
            comparison = {}
            advantages = []
            gaps = []
            recommendations = []

        return AnalyzeCompetitionOutput(
            summary=summary,
            status=status,
            comparison=comparison,
            advantages=advantages,
            gaps=gaps,
            recommendations=recommendations,
            report_markdown=markdown,
            metadata=MCPReportMetadata(
                word_count=word_count,
                section_count=section_count,
                confidence=confidence,
            ),
        )

    @staticmethod
    def _resolve_status(
        *,
        phase: str,
        errors: list[dict[str, Any]],
        evidence_count: int,
        review: dict[str, Any],
        has_report: bool,
    ) -> str:
        if phase in {"failed", "validation_failed", "collection_failed"} or (
            errors and not has_report
        ):
            return "failed"
        if evidence_count == 0:
            return "no_data"
        if (
            errors
            or not review.get("passed_for_output", True)
            or int(review.get("high_issue_count", 0) or 0) > 0
        ):
            return "partial"
        return "completed"
