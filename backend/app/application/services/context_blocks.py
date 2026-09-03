"""Shared Memory + Knowledge Notes context blocks for Planner/Strategy/Report."""

from __future__ import annotations

from typing import Any

from app.domain.entities.knowledge_note import (
    KNOWLEDGE_PROMPT_PREFIX,
    MAX_INJECT_NOTE_CHARS,
)


def _clip(text: str | None, limit: int) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)].rstrip() + "…"

MEMORY_HISTORY_PREFIX = "【项目记忆——历史分析沉淀，非本轮爬取证据】"

# Token budgets (chars) by consumer
STRATEGY_MEMORY_LIMIT = 600
STRATEGY_NOTES_LIMIT = 800
REPORT_MEMORY_LIMIT = 400
REPORT_NOTES_LIMIT = 600
PLANNER_MEMORY_LIMIT = 600
PLANNER_NOTES_LIMIT = 600

STRATEGY_CONTEXT_RULES = (
    "背景使用规则：\n"
    "- 项目记忆与企业笔记**不是**本轮爬取 Evidence，禁止 invent `evidence_refs` / [E00x]\n"
    "- 与本轮证据冲突时以本轮 Evidence 为准，可在 rationale 注明「与历史结论差异」\n"
    "- 仅由记忆/笔记支撑的结论 → confidence=\"low\" 或放入 missing_information；"
    "不得仅凭笔记写高置信 P0/P1\n"
)

REPORT_CONTEXT_RULES = (
    "背景使用规则：\n"
    "- 不新增无来源观点；组织已有分析时若用到笔记，正文标注「（内部笔记）」\n"
    "- 禁止把笔记/记忆伪造成 [E001] 等 Evidence 引用\n"
)


def _format_memory_from_optional(blob: Any, *, limit: int) -> str:
    if not isinstance(blob, dict) or limit <= 0:
        return ""
    parts: list[str] = [MEMORY_HISTORY_PREFIX]
    ents = blob.get("entities") if isinstance(blob.get("entities"), dict) else {}
    company = (ents.get("our_company") or "").strip()
    product = (ents.get("product") or "").strip()
    comps = ents.get("competitors") or []
    if not isinstance(comps, list):
        comps = []
    comps_s = "、".join(str(c).strip() for c in comps if str(c).strip())
    if company or product or comps_s:
        parts.append(f"- 实体：{company or '?'} vs {comps_s or '?'} / {product or '?'}")
    objectives = blob.get("last_objectives") or []
    if isinstance(objectives, list) and objectives:
        parts.append("- 近期目标：" + "；".join(str(o) for o in objectives[:3] if str(o).strip()))
    findings = blob.get("key_findings") or []
    if isinstance(findings, list) and findings:
        parts.append("- 关键结论：")
        count = 0
        for item in findings:
            if count >= 5:
                break
            if isinstance(item, str):
                text = item.strip()
            elif isinstance(item, dict):
                text = str(item.get("text") or "").strip()
            else:
                continue
            if not text:
                continue
            parts.append(f"  - {_clip(text, 200)}")
            count += 1
    questions = blob.get("open_questions") or []
    if isinstance(questions, list) and questions:
        parts.append(
            "- 未决问题：" + "；".join(str(q) for q in questions[:3] if str(q).strip())
        )
    # Fallback to pre-rendered prompt_block if structured fields empty
    body = "\n".join(parts).strip()
    if body == MEMORY_HISTORY_PREFIX:
        pre = str(blob.get("prompt_block") or "").strip()
        if not pre:
            return ""
        if MEMORY_HISTORY_PREFIX not in pre and "项目记忆" not in pre:
            pre = f"{MEMORY_HISTORY_PREFIX}\n{pre}"
        return _clip(pre, limit)
    return _clip(body, limit)


def _format_notes_from_optional(blob: Any, *, limit: int) -> str:
    if not isinstance(blob, dict) or limit <= 0:
        return ""
    pre = str(blob.get("prompt_block") or "").strip()
    if pre:
        if KNOWLEDGE_PROMPT_PREFIX not in pre:
            pre = f"{KNOWLEDGE_PROMPT_PREFIX}\n{pre}"
        return _clip(pre, limit)
    notes = blob.get("notes") or []
    if not isinstance(notes, list) or not notes:
        return ""
    parts: list[str] = [KNOWLEDGE_PROMPT_PREFIX]
    used = len(parts[0])
    for note in notes:
        if not isinstance(note, dict):
            continue
        title = str(note.get("title") or "").strip() or "未命名"
        excerpt = _clip(str(note.get("excerpt") or note.get("body") or ""), MAX_INJECT_NOTE_CHARS)
        tags = note.get("tags") or []
        tag_s = ""
        if isinstance(tags, list) and tags:
            tag_s = f" tags={','.join(str(t) for t in tags[:5])}"
        block = f"- [{title}]{tag_s}\n  {excerpt}"
        if used + len(block) + 1 > limit:
            remain = limit - used - 1
            if remain > 40:
                parts.append(_clip(block, remain))
            break
        parts.append(block)
        used += len(block) + 1
    text = "\n".join(parts).strip()
    return _clip(text, limit) if text != KNOWLEDGE_PROMPT_PREFIX else ""


def build_memory_notes_context(
    optional: dict[str, Any] | None,
    *,
    memory_limit: int,
    notes_limit: int,
) -> str | None:
    """Build Memory + Notes prompt block from launch optional dict.

    Returns None when both empty — callers should leave prompt structure unchanged.
    """
    if not isinstance(optional, dict):
        return None
    parts: list[str] = []
    mem = _format_memory_from_optional(optional.get("project_memory"), limit=memory_limit)
    if mem:
        parts.append(mem)
    notes = _format_notes_from_optional(optional.get("knowledge_notes"), limit=notes_limit)
    if notes:
        parts.append(notes)
    text = "\n\n".join(parts).strip()
    return text or None


def append_context_to_prompt(
    prompt: str,
    context: str | None,
    *,
    rules: str,
) -> str:
    """Append background section only when context is non-empty."""
    if not (context or "").strip():
        return prompt
    return (
        f"{prompt.rstrip()}\n\n"
        f"## 项目背景（非本轮爬取证据）\n"
        f"{context.strip()}\n\n"
        f"{rules}"
    )


def optional_from_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Read launch optional from workflow state (user_input.optional)."""
    if not isinstance(state, dict):
        return {}
    user_input = state.get("user_input") or {}
    if not isinstance(user_input, dict):
        return {}
    optional = user_input.get("optional") or {}
    return optional if isinstance(optional, dict) else {}
