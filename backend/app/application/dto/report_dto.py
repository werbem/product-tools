"""Report DTOs — request/response."""

from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ReportCreateRequest(BaseModel):
    our_company: str = Field(..., min_length=1, description="我方公司名称")
    competitor_company: str = Field(..., min_length=1, description="竞品公司名称")
    product: str = Field(..., min_length=1, description="比对产品名称")
    objective: str = Field(
        default="product_improvement",
        description="分析目标。推荐枚举值: product_improvement, go_to_market, investment_due_diligence, competitive_defense, positioning_switch, partnership_evaluation, feature_benchmark。也支持自定义文本。",
    )
    scene: Optional[str] = Field(
        default=None,
        description="自定义分析场景描述(自由文本)。当用户未使用推荐枚举目标时必填。",
    )
    optional: Optional[dict] = Field(default=None, description="可选上下文")


class ReportCreateResponse(BaseModel):
    task_id: UUID
    status: str = "pending"
    message: str = "分析任务已创建"


class ReportSectionDTO(BaseModel):
    title: str
    content: str
    order: int
    word_count: int


class ReportDetailResponse(BaseModel):
    id: UUID
    task_id: UUID
    our_company: str
    competitor_company: str
    product: str
    objective: str
    markdown: Optional[str] = None
    html: Optional[str] = None
    word_url: Optional[str] = None
    sections: list[ReportSectionDTO] = Field(default_factory=list)
    total_word_count: int = 0
    generated_at: Optional[datetime] = None
    evidence_sources: Optional[list[dict]] = None
    status: Optional[str] = None
    error: Optional[str] = None
    diagnosis: Optional[dict] = None
    created_at: datetime


class ReportListResponse(BaseModel):
    reports: list[ReportDetailResponse]
    total: int
