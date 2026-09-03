"""Collection result DTOs."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class CollectionEvidenceItemDTO(BaseModel):
    id: str = ""
    title: str = ""
    source: str = ""
    source_type: str = "web"
    url: str = ""
    date: str = ""
    content: str = ""
    confidence: str = "medium"
    category: str = ""


class CollectionDetailResponse(BaseModel):
    task_id: UUID
    workflow_kind: str = "intelligence_collection"
    status: str = "pending"
    our_company: str = ""
    product: str = ""
    objective: str = ""
    topic: str = ""
    topic_source: str = ""
    objective_code: str = ""
    markdown: Optional[str] = None
    evidence_items: list[CollectionEvidenceItemDTO] = Field(default_factory=list)
    evidence_count: int = 0
    sources_attempted: int = 0
    sources_succeeded: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime
    error: Optional[str] = None
