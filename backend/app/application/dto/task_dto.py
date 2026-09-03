"""Task DTOs — progress tracking."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PhaseRecordDTO(BaseModel):
    phase: str
    entered_at: datetime
    duration_ms: int = 0
    status: str = "running"
    error: Optional[dict] = None


class TaskProgressResponse(BaseModel):
    task_id: UUID
    status: str
    current_agent: str
    progress: float = Field(..., ge=0.0, le=100.0)
    phase_history: list[PhaseRecordDTO] = Field(default_factory=list)
    estimated_remaining_seconds: Optional[int] = None
    stage_hint: Optional[str] = None
    total_elapsed_s: Optional[float] = None
    error_info: Optional[str] = None
    diagnosis: Optional[dict] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskDecisionRequest(BaseModel):
    checkpoint_id: str
    option_id: str
    comment: Optional[str] = None
