"""Upsert ProjectMemory after Deep / Collection success (Phase 3 V3.1)."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.domain.entities.copilot_common import utc_now
from app.domain.entities.project_memory import (
    ConversationMemorySummary,
    MemoryFinding,
    PeerSourceType,
    ProjectMemory,
    ProjectMemoryEntities,
    _clip,
    upsert_peer_edges,
)
from app.application.services.intent_entities import (
    sanitize_company_name,
    sanitize_competitors,
)
from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
# Strip common section numbering / markdown emphasis for title↔body comparison.
_TITLE_PREFIX_RE = re.compile(
    r"^(?:#{1,6}\s*|"
    r"(?:[一二三四五六七八九十百千]+、)|"
    r"(?:\d+[\.、．]\s*)|"
    r"(?:[（(]?\d+[）)]\s*)|"
    r"(?:[A-Za-z][\.、]\s*))+"
)
_EMPHASIS_RE = re.compile(r"[*_`~]+")


def _normalize_finding_fragment(text: str) -> str:
    """Normalize for title/body equality checks (not for storage)."""
    value = (text or "").strip()
    value = _EMPHASIS_RE.sub("", value)
    value = value.lstrip("#").strip()
    value = _TITLE_PREFIX_RE.sub("", value).strip()
    value = re.sub(r"\s+", "", value)
    value = value.replace("：", ":").rstrip(":：").strip()
    return value.casefold()


def _is_title_variant(line: str, title: str) -> bool:
    """True when line is the same as title or an obvious numbered/emphasized variant."""
    raw_line = (line or "").strip()
    raw_title = (title or "").strip()
    if not raw_line or not raw_title:
        return False
    if raw_line == raw_title:
        return True
    # "Title：Title" / "Title: Title" collapsed leftovers
    if raw_line in {f"{raw_title}：{raw_title}", f"{raw_title}: {raw_title}", f"{raw_title}:{raw_title}"}:
        return True
    norm_line = _normalize_finding_fragment(raw_line)
    norm_title = _normalize_finding_fragment(raw_title)
    if not norm_line or not norm_title:
        return False
    if norm_line == norm_title:
        return True
    # Line is only the title plus a trailing colon
    if norm_line.rstrip(":") == norm_title:
        return True
    return False


def _first_substantive_body_line(lines: list[str], title: str, *, min_len: int = 8) -> str:
    """Pick first body line that is not empty and not a title variant."""
    for raw in lines:
        line = (raw or "").strip()
        if not line:
            continue
        # Drop list/heading markers consistently with prior extractor behavior.
        cleaned = line.lstrip("-*# ").strip()
        if len(cleaned) < min_len:
            continue
        if _is_title_variant(cleaned, title):
            continue
        return cleaned
    return ""


def _compose_finding_text(title: str, body: str) -> str | None:
    """Build finding text only when substantive body exists."""
    title = (title or "").strip()
    body = (body or "").strip()
    if not body:
        return None
    if title and _is_title_variant(body, title):
        return None
    if title:
        return f"{title}：{body}"
    return body


def extract_findings_from_report(
    *,
    markdown: str | None,
    sections: list[dict[str, Any]] | None,
    task_id: str | None,
    limit: int = 5,
) -> list[MemoryFinding]:
    """Rule-based excerpt — no LLM. Prefer section titles + first substantive sentence."""
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
            first = _first_substantive_body_line(content.splitlines(), title)
            text = _compose_finding_text(title, first)
            if not text:
                continue
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
            rest = markdown[match.end() : match.end() + 400]
            body_lines: list[str] = []
            for line in rest.splitlines():
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    break
                body_lines.append(stripped)
            first = _first_substantive_body_line(body_lines, title)
            text = _compose_finding_text(title, first)
            if not text:
                continue
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
    company = sanitize_company_name(our_company)
    comps = sanitize_competitors(comps, company)
    return ProjectMemoryEntities(
        our_company=company,
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

    @staticmethod
    def _schedule_findings_reindex(project_id: str, findings: list[MemoryFinding]) -> None:
        async def _go() -> None:
            from app.application.services.memory_findings_index import memory_findings_index

            await memory_findings_index.reindex(project_id, findings)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_go())
        except RuntimeError:
            try:
                asyncio.run(_go())
            except Exception as exc:
                logger.warning(
                    "memory_findings_reindex_sync_failed project=%s err=%s",
                    project_id,
                    exc,
                )

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
            memory.peer_edges = upsert_peer_edges(
                memory.peer_edges,
                company=entities.our_company,
                competitors=list(entities.competitors),
                product=entities.product,
                source_task_id=task_id,
                source_type="report",
            )
            memory.schema_version = max(int(memory.schema_version or 1), 2)
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
            saved = self._store.upsert(memory)
            self._schedule_findings_reindex(project_id, saved.key_findings)
            return saved
        except Exception:
            logger.exception("MemoryWriter.upsert_from_deep_success failed project=%s", project_id)
            return None

    def record_peer_relations(
        self,
        *,
        project_id: str,
        company: str | None,
        competitors: list[str],
        product: str | None = None,
        source_task_id: str | None = None,
        source_type: PeerSourceType = "user",
        set_as_our_company: bool = True,
    ) -> ProjectMemory | None:
        """Persist peer edges at analysis launch / curated confirm (best-effort)."""
        try:
            company = sanitize_company_name(company)
            comps = sanitize_competitors(list(competitors or []), company)
            if not company or not comps:
                return None
            memory = self._store.get_or_empty(project_id)
            if set_as_our_company:
                memory.entities = memory.entities.merge_nonempty(
                    ProjectMemoryEntities(
                        our_company=company,
                        competitors=comps,
                        product=product,
                    ),
                )
            else:
                memory.entities.competitors = sanitize_competitors(
                    list(memory.entities.competitors) + comps,
                    memory.entities.our_company or company,
                )
            memory.peer_edges = upsert_peer_edges(
                memory.peer_edges,
                company=company,
                competitors=comps,
                product=product,
                source_task_id=source_task_id,
                source_type=source_type,
            )
            memory.schema_version = max(int(memory.schema_version or 1), 2)
            memory.updated_at = utc_now()
            return self._store.upsert(memory)
        except Exception:
            logger.exception("MemoryWriter.record_peer_relations failed project=%s", project_id)
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
            if entities.our_company and entities.competitors:
                memory.peer_edges = upsert_peer_edges(
                    memory.peer_edges,
                    company=entities.our_company,
                    competitors=list(entities.competitors),
                    product=entities.product,
                    source_task_id=task_id,
                    source_type="collection",
                )
                memory.schema_version = max(int(memory.schema_version or 1), 2)
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
            saved = self._store.upsert(memory)
            self._schedule_findings_reindex(project_id, saved.key_findings)
            return saved
        except Exception:
            logger.exception(
                "MemoryWriter.upsert_from_collection_success failed project=%s",
                project_id,
            )
            return None
