"""Unified Research Task shown before Deep / Collection launch."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

FieldSource = Literal["user_input", "system_inferred", "system_default", "unresolved"]
ResearchTaskStatus = Literal["pending", "confirmed", "cancelled"]
RoutedWorkflow = Literal["deep_analysis", "intelligence_collection"]


class SourcedText(BaseModel):
    value: str | None = None
    source: FieldSource = "unresolved"

    @field_validator("value", mode="before")
    @classmethod
    def strip_value(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None


class SourcedItem(BaseModel):
    value: str
    source: FieldSource = "user_input"

    @field_validator("value", mode="before")
    @classmethod
    def strip_value(cls, value: str) -> str:
        return str(value or "").strip()


class ResearchTask(BaseModel):
    """Intent-layer task definition shared by Collection and Deep Analysis."""

    id: str
    status: ResearchTaskStatus = "pending"
    conversation_id: str
    project_id: str
    source_message_id: str | None = None
    confirmation_message_id: str | None = None
    analysis_mode: Literal["fast", "full"] = "fast"
    routed_workflow: RoutedWorkflow
    raw_message: str
    collection_targets: SourcedText = Field(default_factory=SourcedText)
    collection_topics: SourcedText = Field(default_factory=SourcedText)
    research_scope: SourcedText = Field(default_factory=SourcedText)
    analysis_subject: SourcedText = Field(default_factory=SourcedText)
    competitors: list[SourcedItem] = Field(default_factory=list)
    analysis_product: SourcedText = Field(default_factory=SourcedText)
    analysis_goal: SourcedText = Field(default_factory=SourcedText)
    launched_task_id: str | None = None
    launched_report_id: str | None = None
    follow_up_upgrade: bool = False
    follow_up_context: dict[str, Any] = Field(default_factory=dict)

    def competitor_names(self) -> list[str]:
        return [item.value for item in self.competitors if item.value]


class ConfirmResearchTaskRequest(BaseModel):
    collection_targets: str | None = None
    collection_topics: str | None = None
    research_scope: str | None = None
    analysis_subject: str | None = None
    competitors: list[str] | None = None
    analysis_product: str | None = None
    analysis_goal: str | None = None
    analysis_mode: Literal["fast", "full"] | None = None

    @field_validator(
        "collection_targets",
        "collection_topics",
        "research_scope",
        "analysis_subject",
        "analysis_product",
        "analysis_goal",
        mode="before",
    )
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @field_validator("competitors", mode="before")
    @classmethod
    def normalize_competitors(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        seen: set[str] = set()
        out: list[str] = []
        for item in value:
            cleaned = str(item or "").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                out.append(cleaned)
        return out
