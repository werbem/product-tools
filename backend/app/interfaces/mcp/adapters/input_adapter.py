"""Translate MCP input schemas into adapter-level internal payloads.

Phase 1 keeps this mapping at the payload level. Workflow state creation and
subgraph execution are wired in the next phase.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.infrastructure.workflow.state import create_initial_state
from app.application.dto.agent_dto import (
    CompanyInfoDTO,
    EvidenceBundleDTO,
    EvidenceItemDTO,
    ProductInfoDTO,
)
from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionInput,
    CollectCompetitorIntelligenceInput,
)


class CollectInputAdapter:
    """Map collect_competitor_intelligence input to an internal payload."""

    def to_initial_state(
        self,
        input_data: CollectCompetitorIntelligenceInput,
    ) -> dict[str, Any]:
        return create_initial_state(
            {
                "our_company": input_data.our_company,
                "competitor_company": input_data.competitor_company,
                "product": input_data.product,
                "objective": input_data.objective,
                "optional": {
                    "dimensions": input_data.dimensions,
                    "source_types": input_data.source_types,
                    "max_evidence": input_data.max_evidence,
                    "workflow_kind": "intelligence_collection",
                    "skip_evidence_evaluation": True,
                },
            }
        )

    def to_internal_payload(
        self,
        input_data: CollectCompetitorIntelligenceInput,
    ) -> dict[str, Any]:
        return {
            "our_company": input_data.our_company,
            "competitor_company": input_data.competitor_company,
            "product": input_data.product,
            "objective": input_data.objective,
            "dimensions": input_data.dimensions,
            "source_types": input_data.source_types,
            "max_evidence": input_data.max_evidence,
        }


class AnalyzeInputAdapter:
    """Map analyze_competition input to internal analysis state."""

    def to_internal_payload(
        self,
        input_data: AnalyzeCompetitionInput,
    ) -> dict[str, Any]:
        return {
            "our_company": input_data.our_company,
            "competitor_company": input_data.competitor_company,
            "product": input_data.product,
            "objective": input_data.objective,
            "intelligence": input_data.intelligence,
        }

    def to_internal_state(
        self,
        input_data: AnalyzeCompetitionInput,
    ) -> dict[str, Any]:
        state = create_initial_state(
            {
                "our_company": input_data.our_company,
                "competitor_company": input_data.competitor_company,
                "product": input_data.product,
                "objective": input_data.objective,
            }
        )

        if not input_data.intelligence:
            return state

        intelligence = input_data.intelligence
        raw_evidence = intelligence.get("evidence") or intelligence.get("evidenceItem") or []
        evidence_items = [self._map_evidence_item(item) for item in raw_evidence]
        dimensions = intelligence.get("dimensions") or []
        clusters = intelligence.get("clusters") or []

        state["validated_input"] = {
            "is_valid": True,
            "our_company": input_data.our_company,
            "competitor_company": input_data.competitor_company,
            "product": input_data.product,
            "objective": input_data.objective,
        }
        state["research_plan"] = {
            "objective": input_data.objective,
            "analysis_scope": dimensions,
            "research_tasks": [],
            "required_sources": [],
            "workflow": [],
            "estimated_complexity": "moderate",
        }
        state["evidence_bundle"] = self._build_evidence_bundle(
            input_data=input_data,
            evidence_items=evidence_items,
        )
        state["clusters"] = clusters
        return state

    def _build_evidence_bundle(
        self,
        input_data: AnalyzeCompetitionInput,
        evidence_items: list[EvidenceItemDTO],
    ) -> dict[str, Any]:
        bundle = EvidenceBundleDTO(
            our_company=CompanyInfoDTO(
                name=input_data.our_company,
                data_quality="provided" if evidence_items else "no_data",
            ),
            competitor_company=CompanyInfoDTO(
                name=input_data.competitor_company,
                data_quality="provided" if evidence_items else "no_data",
            ),
            our_product=ProductInfoDTO(
                name=input_data.product,
                data_quality="provided" if evidence_items else "no_data",
            ),
            competitor_product=ProductInfoDTO(
                name=input_data.product,
                data_quality="provided" if evidence_items else "no_data",
            ),
            evidence_items=evidence_items,
            sources_used=[
                {
                    "source_id": item.id or f"src_{i:03d}",
                    "domain": urlparse(item.url).netloc if item.url else "",
                    "url": item.url,
                    "title": item.title,
                    "summary": (item.content or "")[:300],
                    "source_type": item.source_type,
                    "date": item.date,
                }
                for i, item in enumerate(evidence_items)
            ],
            references=[
                {"url": item.url, "title": item.title}
                for item in evidence_items
                if item.url
            ],
            quality_score={
                "overall": min(100, len(evidence_items) * 10),
                "coverage": min(100, len(evidence_items) * 10),
                "freshness": 70,
            },
        )
        return bundle.model_dump()

    @staticmethod
    def _map_evidence_item(item: dict[str, Any]) -> EvidenceItemDTO:
        source = item.get("source") or {}
        quality = item.get("quality") or {}
        quality_score = None
        if quality:
            quality_score = {
                "authority_score": quality.get("authority", 0.0),
                "freshness_score": quality.get("freshness", 0.0),
                "relevance_score": quality.get("relevance", 0.0),
                "reliability_score": quality.get("reliability", 0.0),
                "overall_confidence": quality.get("overall", 0.0),
            }

        return EvidenceItemDTO(
            id=str(item.get("finding_id", "")),
            title=str(source.get("name") or item.get("finding", ""))[:200],
            source=str(source.get("name", "")),
            source_type=str(source.get("type", "web")),
            url=str(source.get("url", "")),
            date=str(source.get("published_at", "")),
            content=str(item.get("finding", "")),
            confidence=str(item.get("confidence", "medium")),
            category=str(item.get("dimension", "")),
            quality_score=quality_score,
        )
