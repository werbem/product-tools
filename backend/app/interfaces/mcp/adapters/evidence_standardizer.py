"""Normalize evidence items into the external MCP evidence shape."""

from __future__ import annotations

from typing import Any

from app.interfaces.mcp.schemas import (
    MCPEvidenceItem,
    MCPEvidenceQuality,
    MCPEvidenceSource,
)


class EvidenceStandardizer:
    """Convert internal evidence dictionaries to MCPEvidenceItem models."""

    def standardize(
        self,
        evidence_items: list[dict[str, Any]],
    ) -> list[MCPEvidenceItem]:
        return [self.standardize_one(item) for item in evidence_items]

    def standardize_one(self, item: dict[str, Any]) -> MCPEvidenceItem:
        quality = item.get("quality_score")
        parsed_quality = None
        if isinstance(quality, dict):
            parsed_quality = MCPEvidenceQuality(
                authority=float(quality.get("authority_score", 0.0) or 0.0),
                freshness=float(quality.get("freshness_score", 0.0) or 0.0),
                relevance=float(quality.get("relevance_score", 0.0) or 0.0),
                reliability=float(quality.get("reliability_score", 0.0) or 0.0),
                overall=float(quality.get("overall_confidence", 0.0) or 0.0),
            )

        extracted_at = item.get("extracted_at")
        if hasattr(extracted_at, "isoformat"):
            extracted_at = extracted_at.isoformat()

        return MCPEvidenceItem(
            finding_id=str(item.get("id", "")),
            dimension=str(item.get("category", "")),
            finding=str(item.get("content", "")),
            source=MCPEvidenceSource(
                name=str(item.get("source", "")),
                type=str(item.get("source_type", "")),
                url=str(item.get("url", "")),
                published_at=str(item.get("date", "")),
            ),
            confidence=str(item.get("confidence", "medium")),
            quality=parsed_quality,
            created_at=str(extracted_at or item.get("date", "") or ""),
        )
