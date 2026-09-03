"""Project Knowledge Notes — user-authored internal notes (Phase 3 V3.2)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.domain.entities.copilot_common import from_iso, utc_now

MAX_TITLE_CHARS = 100
MAX_BODY_CHARS = 8000
MAX_NOTES_PER_PROJECT = 50
MAX_TAGS = 20
MAX_TAG_CHARS = 40
MAX_INJECT_NOTE_CHARS = 400
MAX_INJECT_TOTAL_CHARS = 1200
DEFAULT_SEARCH_LIMIT = 5
DEFAULT_INJECT_TOP_K = 3

KNOWLEDGE_PROMPT_PREFIX = (
    "【企业/项目知识笔记——非公开爬取证据，引用时请标明来源为内部笔记】"
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+|[a-z0-9]+", re.IGNORECASE)


def _clip(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"


@dataclass
class KnowledgeNote:
    id: str
    project_id: str
    title: str
    body: str
    tags: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def enforce_limits(self) -> None:
        self.title = _clip(self.title, MAX_TITLE_CHARS)
        self.body = _clip(self.body, MAX_BODY_CHARS)
        tags: list[str] = []
        for tag in self.tags:
            t = _clip(str(tag), MAX_TAG_CHARS)
            if t and t not in tags:
                tags.append(t)
            if len(tags) >= MAX_TAGS:
                break
        self.tags = tags

    def to_dict(self) -> dict[str, Any]:
        self.enforce_limits()
        return {
            "id": self.id,
            "project_id": self.project_id,
            "title": self.title,
            "body": self.body,
            "tags": list(self.tags),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> KnowledgeNote:
        created = data.get("created_at")
        updated = data.get("updated_at")
        tags = data.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        note = cls(
            id=str(data["id"]),
            project_id=str(data["project_id"]),
            title=str(data.get("title") or ""),
            body=str(data.get("body") or ""),
            tags=[str(t) for t in tags],
            created_at=from_iso(created) if isinstance(created, str) else utc_now(),
            updated_at=from_iso(updated) if isinstance(updated, str) else utc_now(),
        )
        note.enforce_limits()
        return note


def score_note(note: KnowledgeNote, query: str) -> float:
    """Case-insensitive keyword score over title/body/tags (CJK substring OK)."""
    q = (query or "").strip().lower()
    if not q:
        return 0.0
    title = (note.title or "").lower()
    body = (note.body or "").lower()
    tags = " ".join(note.tags or []).lower()
    score = 0.0
    if q in title:
        score += 10.0
    if q in tags:
        score += 8.0
    if q in body:
        score += 5.0
    tokens = _TOKEN_RE.findall(q)
    # Also try 2-gram CJK slices for short Chinese queries
    for i in range(len(q)):
        for length in (2, 3, 4):
            if i + length <= len(q):
                piece = q[i : i + length]
                if _TOKEN_RE.fullmatch(piece) and piece not in tokens:
                    tokens.append(piece)
    seen: set[str] = set()
    for token in tokens:
        if len(token) < 1 or token in seen:
            continue
        seen.add(token)
        if token in title:
            score += 3.0
        if token in tags:
            score += 2.0
        if token in body:
            score += 1.0
    return score


def format_knowledge_prompt_block(
    notes: list[KnowledgeNote] | None,
    *,
    limit: int = MAX_INJECT_TOTAL_CHARS,
) -> str:
    if not notes:
        return ""
    parts: list[str] = [KNOWLEDGE_PROMPT_PREFIX]
    used = len(parts[0])
    for note in notes:
        excerpt = _clip(note.body, MAX_INJECT_NOTE_CHARS)
        tags = f" tags={','.join(note.tags)}" if note.tags else ""
        block = f"- [{note.title}]{tags}\n  {excerpt}"
        if used + len(block) + 1 > limit:
            remain = limit - used - 1
            if remain > 40:
                parts.append(_clip(block, remain))
            break
        parts.append(block)
        used += len(block) + 1
    text = "\n".join(parts).strip()
    return _clip(text, limit)


def notes_to_optional_dict(notes: list[KnowledgeNote] | None) -> dict[str, Any] | None:
    if not notes:
        return None
    return {
        "notes": [
            {
                "id": n.id,
                "title": n.title,
                "excerpt": _clip(n.body, MAX_INJECT_NOTE_CHARS),
                "tags": list(n.tags),
            }
            for n in notes
        ],
        "prompt_block": format_knowledge_prompt_block(notes),
    }
