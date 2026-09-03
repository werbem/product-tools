"""Upsert ProjectMemory after Deep / Collection success (Phase 3 V3.1)."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.domain.entities.copilot_common import utc_now
from app.domain.entities.project_memory import (
    ConversationMemorySummary,
    MemoryFinding,
    ProjectMemory,
    ProjectMemoryEntities,
    _clip,
)
from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)


def extract_findings_from_report(
    *,
    markdown: str | None,
    sections: list[dict[str, Any]] | None,
    task_id: str | None,
    limit: int = 5,
) -> list[MemoryFinding]:
    """Rule-based excerpt — no LLM. Prefer section titles + first sentence."""
    findings: list[MemoryFinding] = []
    now = utc_now()

    if sections:
        for section in sections:
            if len(findings) >= limit:
                break
            if not isinstance(section, dict):
                continue
            title = str(section.get("title") or "").strip()
            content = str(section.get("content") or "").strip()
            first = ""
            for line in content.splitlines():
                line = line.strip().lstrip("-*# ").strip()
                if len(line) >= 8:
                    first = line
                    break
            text = f"{title}：{first}" if title and first else (title or first)
            if text:
                findings.append(
                    MemoryFinding(
                        text=_clip(text, 200),
                        source_task_id=task_id,
                        source_type="report",
                        updated_at=now,
                    ),
                )

    if len(findings) < limit and markdown:
        for match in _HEADING_RE.finditer(markdown):
            if len(findings) >= limit:
                break
            title = match.group(1).strip()
            if not title or title.startswith("目录"):
                continue
            # first non-empty line after heading
            rest = markdown[match.end() : match.end() + 400]
            first = ""
            for line in rest.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                first = line.lstrip("-* ").strip()
                break
            text = f"{title}：{first}" if first else title
            findings.append(
                MemoryFinding(
                    text=_clip(text, 200),
                    source_task_id=task_id,
                    source_type="report",
                    updated_at=now,
                ),
            )

    return findings[:limit]


def extract_findings_from_collection(
    *,
    topic: str | None,
    evidence_titles: list[str],
    task_id: str | None,
    limit: int = 5,
) -> list[MemoryFinding]:
    now = utc_now()
    findings: list[MemoryFinding] = []
    if topic:
        findings.append(
            MemoryFinding(
                text=_clip(f"收集主题：{topic}", 200),
                source_task_id=task_id,
                source_type="collection",
                updated_at=now,
            ),
        )
    for title in evidence_titles:
        if len(findings) >= limit:
            break
        t = str(title or "").strip()
        if not t:
            continue
        findings.append(
            MemoryFinding(
                text=_clip(t, 200),
                source_task_id=task_id,
                source_type="collection",
                updated_at=now,
            ),
        )
    return findings[:limit]


def _entities_from_validated_or_body(
    *,
    our_company: str | None,
    competitor_company: str | None,
    competitors: list[str] | None,
    product: str | None,
) -> ProjectMemoryEntities:
    comps = [c for c in (competitors or []) if c]
    if not comps and competitor_company:
        comps = [p.strip() for p in re.split(r"[、,/|]", competitor_company) if p.strip()]
        # Drop placeholder used by collection mapper
        comps = [c for c in comps if c not in ("公开市场与主要竞品",)]
    return ProjectMemoryEntities(
        our_company=(our_company or None),
        competitors=comps,
        product=(product or None),
    )


def _prepend_findings(
    existing: list[MemoryFinding],
    new_items: list[MemoryFinding],
) -> list[MemoryFinding]:
    """Newest first; de-dupe by text prefix."""
    seen: set[str] = set()
    out: list[MemoryFinding] = []
    for item in list(new_items) + list(existing):
        key = item.text[:40]
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= 10:
            break
    return out


class MemoryWriter:
    def __init__(self, store: ProjectMemoryStore | None = None) -> None:
        self._store = store or ProjectMemoryStore()

    def upsert_from_deep_success(
        self,
        *,
        project_id: str,
        conversation_id: str | None,
        task_id: str,
        our_company: str,
        competitor_company: str,
        product: str,
        objective: str | None = None,
        scene: str | None = None,
        competitors: list[str] | None = None,
        markdown: str | None = None,
        sections: list[dict[str, Any]] | None = None,
        validated_input: dict[str, Any] | None = None,
    ) -> ProjectMemory | None:
        try:
            memory = self._store.get_or_empty(project_id)
            entities = _entities_from_validated_or_body(
                our_company=our_company,
                competitor_company=competitor_company,
                competitors=competitors,
                product=product,
            )
            memory.entities = memory.entities.merge_nonempty(entities)
            obj = (scene or objective or "").strip()
            if obj:
                memory.last_objectives = [obj] + [
                    o for o in memory.last_objectives if o != obj
                ]
            new_findings = extract_findings_from_report(
                markdown=markdown,
                sections=sections,
                task_id=task_id,
            )
            memory.key_findings = _prepend_findings(memory.key_findings, new_findings)
            memory.last_report_id = task_id
            memory.last_task_id = task_id
            memory.last_workflow_type = "competitive_analysis"
            if conversation_id:
                summary_bits = [
                    f"Deep 分析完成：{our_company} vs {competitor_company} / {product}",
                ]
                if new_findings:
                    summary_bits.append("要点：" + "；".join(f.text for f in new_findings[:3]))
                memory.conversation_summaries[conversation_id] = ConversationMemorySummary(
                    last_workflow_type="competitive_analysis",
                    summary=" ".join(summary_bits),
                    validated_input=dict(validated_input) if validated_input else {
                        "our_company": our_company,
                        "competitor_company": competitor_company,
                        "competitors": list(competitors or []),
                        "product": product,
                        "objective": objective,
                        "scene": scene,
                    },
                    updated_at=utc_now(),
                )
            memory.updated_at = utc_now()
            return self._store.upsert(memory)
        except Exception:
            logger.exception("MemoryWriter.upsert_from_deep_success failed project=%s", project_id)
            return None

    def upsert_from_collection_success(
        self,
        *,
        project_id: str,
        conversation_id: str | None,
        task_id: str,
        our_company: str | None,
        product: str | None,
        topic: str | None = None,
        objective: str | None = None,
        evidence_titles: list[str] | None = None,
        competitor_company: str | None = None,
    ) -> ProjectMemory | None:
        """Does not rely on analysis_started.validated_input (Collection never writes it)."""
        try:
            memory = self._store.get_or_empty(project_id)
            entities = _entities_from_validated_or_body(
                our_company=our_company,
                competitor_company=competitor_company,
                competitors=None,
                product=product,
            )
            memory.entities = memory.entities.merge_nonempty(entities)
            obj = (topic or objective or "").strip()
            if obj:
                memory.last_objectives = [obj] + [
                    o for o in memory.last_objectives if o != obj
                ]
            new_findings = extract_findings_from_collection(
                topic=topic,
                evidence_titles=list(evidence_titles or []),
                task_id=task_id,
            )
            memory.key_findings = _prepend_findings(memory.key_findings, new_findings)
            memory.last_collection_id = task_id
            memory.last_task_id = task_id
            memory.last_workflow_type = "research"
            if conversation_id:
                summary_bits = [
                    f"信息收集完成：{our_company or '?'} · {product or '?'}",
                ]
                if topic:
                    summary_bits.append(f"主题：{topic}")
                memory.conversation_summaries[conversation_id] = ConversationMemorySummary(
                    last_workflow_type="research",
                    summary=" ".join(summary_bits),
                    validated_input={
                        "our_company": our_company,
                        "product": product,
                        "topic": topic,
                    },
                    updated_at=utc_now(),
                )
            memory.updated_at = utc_now()
            return self._store.upsert(memory)
        except Exception:
            logger.exception(
                "MemoryWriter.upsert_from_collection_success failed project=%s",
                project_id,
            )
            return None
