"""Project Memory — cross-conversation compressed context (Phase 3 V3.1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from app.domain.entities.copilot_common import from_iso, utc_now

# Hard size limits — never store full report markdown
MAX_KEY_FINDINGS = 10
MAX_FINDING_CHARS = 200
MAX_LAST_OBJECTIVES = 5
MAX_OPEN_QUESTIONS = 5
MAX_CONVERSATION_SUMMARIES = 10
MAX_CONVERSATION_SUMMARY_CHARS = 500
MAX_MEMORY_PROMPT_CHARS = 800


SourceType = Literal["report", "collection", "manual"]


def _clip(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


@dataclass
class ProjectMemoryEntities:
    our_company: str | None = None
    competitors: list[str] = field(default_factory=list)
    product: str | None = None
    industry: str | None = None

    def merge_nonempty(self, other: ProjectMemoryEntities) -> ProjectMemoryEntities:
        """Non-empty fields from other overwrite self."""
        comps = list(other.competitors) if other.competitors else list(self.competitors)
        return ProjectMemoryEntities(
            our_company=(other.our_company or self.our_company),
            competitors=comps,
            product=(other.product or self.product),
            industry=(other.industry or self.industry),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "our_company": self.our_company,
            "competitors": list(self.competitors),
            "product": self.product,
            "industry": self.industry,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ProjectMemoryEntities:
        raw = data or {}
        comps = raw.get("competitors") or []
        if not isinstance(comps, list):
            comps = []
        return cls(
            our_company=(str(raw["our_company"]).strip() or None) if raw.get("our_company") else None,
            competitors=[str(c).strip() for c in comps if str(c).strip()],
            product=(str(raw["product"]).strip() or None) if raw.get("product") else None,
            industry=(str(raw["industry"]).strip() or None) if raw.get("industry") else None,
        )


@dataclass
class MemoryFinding:
    text: str
    source_task_id: str | None = None
    source_type: SourceType = "manual"
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": _clip(self.text, MAX_FINDING_CHARS),
            "source_task_id": self.source_task_id,
            "source_type": self.source_type,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MemoryFinding:
        ts = data.get("updated_at")
        return cls(
            text=_clip(str(data.get("text") or ""), MAX_FINDING_CHARS),
            source_task_id=str(data["source_task_id"]) if data.get("source_task_id") else None,
            source_type=data.get("source_type") or "manual",  # type: ignore[arg-type]
            updated_at=from_iso(ts) if isinstance(ts, str) else utc_now(),
        )


@dataclass
class ConversationMemorySummary:
    last_workflow_type: str | None = None
    summary: str = ""
    validated_input: dict[str, Any] | None = None
    updated_at: datetime = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_workflow_type": self.last_workflow_type,
            "summary": _clip(self.summary, MAX_CONVERSATION_SUMMARY_CHARS),
            "validated_input": dict(self.validated_input) if self.validated_input else None,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConversationMemorySummary:
        ts = data.get("updated_at")
        vi = data.get("validated_input")
        return cls(
            last_workflow_type=data.get("last_workflow_type"),
            summary=_clip(str(data.get("summary") or ""), MAX_CONVERSATION_SUMMARY_CHARS),
            validated_input=dict(vi) if isinstance(vi, dict) else None,
            updated_at=from_iso(ts) if isinstance(ts, str) else utc_now(),
        )


@dataclass
class ProjectMemory:
    project_id: str
    entities: ProjectMemoryEntities = field(default_factory=ProjectMemoryEntities)
    last_objectives: list[str] = field(default_factory=list)
    key_findings: list[MemoryFinding] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    last_report_id: str | None = None
    last_collection_id: str | None = None
    last_task_id: str | None = None
    last_workflow_type: str | None = None
    conversation_summaries: dict[str, ConversationMemorySummary] = field(default_factory=dict)
    schema_version: int = 1
    updated_at: datetime = field(default_factory=utc_now)

    @classmethod
    def empty(cls, project_id: str) -> ProjectMemory:
        return cls(project_id=project_id)

    def enforce_limits(self) -> None:
        self.last_objectives = [
            _clip(o, 120) for o in self.last_objectives if str(o).strip()
        ][:MAX_LAST_OBJECTIVES]
        self.open_questions = [
            _clip(q, 120) for q in self.open_questions if str(q).strip()
        ][:MAX_OPEN_QUESTIONS]
        self.key_findings = self.key_findings[:MAX_KEY_FINDINGS]
        for finding in self.key_findings:
            finding.text = _clip(finding.text, MAX_FINDING_CHARS)
        # Keep newest conversation summaries
        if len(self.conversation_summaries) > MAX_CONVERSATION_SUMMARIES:
            ordered = sorted(
                self.conversation_summaries.items(),
                key=lambda kv: kv[1].updated_at,
                reverse=True,
            )[:MAX_CONVERSATION_SUMMARIES]
            self.conversation_summaries = dict(ordered)
        for summary in self.conversation_summaries.values():
            summary.summary = _clip(summary.summary, MAX_CONVERSATION_SUMMARY_CHARS)

    def to_dict(self) -> dict[str, Any]:
        self.enforce_limits()
        return {
            "project_id": self.project_id,
            "entities": self.entities.to_dict(),
            "last_objectives": list(self.last_objectives),
            "key_findings": [f.to_dict() for f in self.key_findings],
            "open_questions": list(self.open_questions),
            "last_report_id": self.last_report_id,
            "last_collection_id": self.last_collection_id,
            "last_task_id": self.last_task_id,
            "last_workflow_type": self.last_workflow_type,
            "conversation_summaries": {
                cid: s.to_dict() for cid, s in self.conversation_summaries.items()
            },
            "schema_version": self.schema_version,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectMemory:
        findings_raw = data.get("key_findings") or []
        summaries_raw = data.get("conversation_summaries") or {}
        ts = data.get("updated_at")
        memory = cls(
            project_id=str(data["project_id"]),
            entities=ProjectMemoryEntities.from_dict(data.get("entities")),
            last_objectives=list(data.get("last_objectives") or []),
            key_findings=[
                MemoryFinding.from_dict(f) for f in findings_raw if isinstance(f, dict)
            ],
            open_questions=list(data.get("open_questions") or []),
            last_report_id=data.get("last_report_id"),
            last_collection_id=data.get("last_collection_id"),
            last_task_id=data.get("last_task_id"),
            last_workflow_type=data.get("last_workflow_type"),
            conversation_summaries={
                str(cid): ConversationMemorySummary.from_dict(s)
                for cid, s in summaries_raw.items()
                if isinstance(s, dict)
            },
            schema_version=int(data.get("schema_version") or 1),
            updated_at=from_iso(ts) if isinstance(ts, str) else utc_now(),
        )
        memory.enforce_limits()
        return memory


def format_memory_prompt_block(memory: ProjectMemory | None, *, limit: int = MAX_MEMORY_PROMPT_CHARS) -> str:
    """Compact markdown for prompts (Intent/follow_up/Planner/query)."""
    if not memory:
        return ""
    parts: list[str] = ["## 项目记忆（历史结论，需结合新问题复核）"]
    ent = memory.entities
    if ent.our_company or ent.product or ent.competitors:
        comps = "、".join(ent.competitors) if ent.competitors else "—"
        parts.append(
            f"- 实体：{ent.our_company or '?'} vs {comps} / {ent.product or '?'}"
        )
    if memory.last_objectives:
        parts.append("- 近期目标：" + "；".join(memory.last_objectives[:3]))
    if memory.key_findings:
        parts.append("- 关键结论：")
        for finding in memory.key_findings[:5]:
            parts.append(f"  - {finding.text}")
    if memory.open_questions:
        parts.append("- 未决问题：" + "；".join(memory.open_questions[:3]))
    text = "\n".join(parts).strip()
    return _clip(text, limit)


def memory_to_optional_dict(memory: ProjectMemory | None) -> dict[str, Any] | None:
    if not memory:
        return None
    return {
        "entities": memory.entities.to_dict(),
        "key_findings": [f.text for f in memory.key_findings[:5]],
        "last_objectives": list(memory.last_objectives[:3]),
        "open_questions": list(memory.open_questions[:3]),
        "last_workflow_type": memory.last_workflow_type,
        "prompt_block": format_memory_prompt_block(memory, limit=600),
    }
