"""Follow-up orchestration — short answer with prior context, or upgrade to deep analysis."""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.domain.entities.message import Message
from app.infrastructure.llm.client import LLMClient, LLMResponse, llm_client
from app.infrastructure.persistence import task_report_runtime

logger = logging.getLogger(__name__)

_UPGRADE_PATTERN = re.compile(
    r"完整报告|继续出报告|全面对比|补充进报告|出一份完整|完整竞品分析|"
    r"完整对比报告|继续.{0,8}报告|生成完整报告|"
    r"full\s+report|complete\s+(?:comparison|report)",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = """你是竞品分析助手的追问模块。
必须基于「上轮上下文」回答用户新问题：
- 用要点列表或 ≤600 字短答
- 不得编造上下文中没有的数据或链接
- 上下文不足时明确说明缺失
- 不要输出十三章完整报告结构
- 对日期未知/historical 材料不要断言「最新/近期」
- 若引用项目记忆中的关键结论，须标注「历史结论，需结合新问题」
- 若引用企业/项目知识笔记，须标明来源为「内部笔记」，不得伪造成公开证据"""

_MAX_REPORT_CHARS = 2800
_MAX_MSG_CHARS = 1200
_MAX_CONTEXT_MESSAGES = 8


class FollowUpResult(BaseModel):
    upgrade_to_analysis: bool = False
    answer_markdown: str = ""
    context_summary: str = ""
    prior_task_id: str | None = None
    prior_report_id: str | None = None
    follow_up_mode: str = "short_answer"  # short_answer | upgrade_analysis | no_prior
    confidence: float = 0.6
    metadata: dict[str, Any] = Field(default_factory=dict)


LlmGenerateFn = Callable[..., Awaitable[LLMResponse]]


def message_has_prior_artifact(messages: list[Message] | None) -> bool:
    """True when conversation already has analysis/query/collection output to follow up on."""
    for message in reversed(list(messages or [])):
        if message.task_id:
            return True
        meta = message.metadata or {}
        msg_type = str(meta.get("message_type") or "")
        if msg_type in ("analysis_started", "query_answered", "follow_up_answered"):
            return True
        if meta.get("workflow_type") in (
            "deep_analysis",
            "intelligence_collection",
            "information_query",
            "competitive_analysis",
            "research",
            "follow_up",
        ):
            content = message.content or ""
            if msg_type == "query_answered" or len(content) >= 80:
                return True
            if message.task_id or meta.get("task_id") or meta.get("prior_task_id"):
                return True
        if msg_type == "query_answered" and (message.content or "").strip():
            return True
    return False


def _strip_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _intent_has_deep_entities(data: dict[str, Any] | None) -> bool:
    """company + (product OR scene) — enough to recover a Deep launch base."""
    if not isinstance(data, dict):
        return False
    company = _strip_text(data.get("company") or data.get("our_company"))
    product = _strip_text(data.get("product"))
    scene = _strip_text(data.get("scene"))
    return bool(company and (product or scene))


def _is_deep_analysis_launch_message(meta: dict[str, Any]) -> bool:
    """True for Deep / competitive analysis_started — not collection or short follow_up."""
    msg_type = _strip_text(meta.get("message_type"))
    wf = _strip_text(meta.get("workflow_type") or meta.get("workflow_kind"))
    if wf in ("intelligence_collection", "research", "information_query", "follow_up", "simple_question"):
        return False
    if msg_type == "analysis_started":
        return wf in ("", "deep_analysis", "competitive_analysis") or not wf
    return wf in ("deep_analysis", "competitive_analysis")


def _competitors_from_snapshot(snap: dict[str, Any]) -> list[str]:
    raw = snap.get("competitors")
    if isinstance(raw, list):
        return [str(c).strip() for c in raw if str(c).strip()]
    competitor_company = _strip_text(snap.get("competitor_company"))
    if competitor_company:
        return [p for p in re.split(r"[、,/|]", competitor_company) if p.strip()]
    return []


def _intent_dict_from_validated_input(snap: dict[str, Any]) -> dict[str, Any] | None:
    company = _strip_text(snap.get("our_company") or snap.get("company"))
    product = _strip_text(snap.get("product"))
    scene = _strip_text(snap.get("scene"))
    if not company or not (product or scene):
        return None
    objective = _strip_text(snap.get("objective")) or scene or "product_improvement"
    return {
        "type": "competitive_analysis",
        "company": company,
        "competitors": _competitors_from_snapshot(snap),
        "product": product or scene,
        "objective": objective,
        "scene": scene or None,
        "confidence": float(snap.get("confidence") or 0.9),
        "needs_clarification": False,
        "raw_message": _strip_text(snap.get("raw_message")),
    }


def select_best_prior_analysis_intent(
    messages: list[Message] | None,
) -> dict[str, Any] | None:
    """Pick the best prior Deep-analysis intent (reverse scan).

    Priority:
      1. analysis_started / deep_analysis with validated_input snapshot
      2. same messages with complete metadata.intent (company + product|scene)
    Explicitly ignore empty follow_up / query / question intents.
    """
    for message in reversed(list(messages or [])):
        meta = message.metadata or {}
        if not _is_deep_analysis_launch_message(meta):
            continue
        snap = meta.get("validated_input")
        if isinstance(snap, dict):
            from_snap = _intent_dict_from_validated_input(snap)
            if from_snap:
                return from_snap
        intent = meta.get("intent")
        if isinstance(intent, dict) and _intent_has_deep_entities(intent):
            out = dict(intent)
            # Normalize product from scene when product missing
            if not _strip_text(out.get("product")) and _strip_text(out.get("scene")):
                out["product"] = _strip_text(out.get("scene"))
            return out
    return None


def merge_intent_for_upgrade(
    base: dict[str, Any] | IntentUnderstandingResult,
    overlay: IntentUnderstandingResult | None,
) -> IntentUnderstandingResult:
    """Merge overlay (current upgrade turn) onto prior analysis base; empty overlay keeps base."""
    base_d = base.model_dump() if isinstance(base, IntentUnderstandingResult) else dict(base)

    def _pick(overlay_val: Any, base_val: Any) -> Any:
        if overlay_val is None:
            return base_val
        if isinstance(overlay_val, str) and not overlay_val.strip():
            return base_val
        if isinstance(overlay_val, list) and not overlay_val:
            return base_val
        return overlay_val

    company = _pick(overlay.company if overlay else None, base_d.get("company"))
    product = _pick(overlay.product if overlay else None, base_d.get("product"))
    competitors = _pick(
        list(overlay.competitors) if overlay else None,
        list(base_d.get("competitors") or []),
    )
    objective = _pick(overlay.objective if overlay else None, base_d.get("objective"))
    scene = _strip_text(base_d.get("scene"))
    if not _strip_text(product) and scene:
        product = scene
    if not _strip_text(objective):
        objective = scene or "product_improvement"
    raw = _pick(
        overlay.raw_message if overlay else None,
        base_d.get("raw_message") or "",
    )
    confidence = float(
        (overlay.confidence if overlay and overlay.confidence is not None else None)
        or base_d.get("confidence")
        or 0.8
    )
    return IntentUnderstandingResult(
        type="competitive_analysis",
        company=_strip_text(company) or None,
        competitors=[str(c).strip() for c in (competitors or []) if str(c).strip()],
        product=_strip_text(product) or None,
        objective=_strip_text(objective) or "product_improvement",
        confidence=confidence,
        needs_clarification=False,
        raw_message=_strip_text(raw) or (overlay.raw_message if overlay else "") or "",
    )


def extract_prior_refs(messages: list[Message] | None) -> dict[str, Any]:
    """Locate latest task/report, textual prior blob, and best analysis intent.

    Intent recovery does **not** use the nearest message that merely has an
    ``intent`` key (follow_up short answers often store an empty intent and
    would overwrite the original analysis_started entities).
    """
    prior_task_id: str | None = None
    prior_report_id: str | None = None
    prior_assistant_blob = ""

    for message in reversed(list(messages or [])):
        meta = message.metadata or {}
        tid = message.task_id or meta.get("task_id") or meta.get("prior_task_id")
        rid = meta.get("report_id") or meta.get("prior_report_id")
        if tid and not prior_task_id:
            prior_task_id = str(tid)
            if rid:
                prior_report_id = str(rid)
        if message.role == "assistant" and not prior_assistant_blob:
            msg_type = str(meta.get("message_type") or "")
            content = (message.content or "").strip()
            if msg_type in ("query_answered", "follow_up_answered") and content:
                prior_assistant_blob = content[:_MAX_MSG_CHARS]
            elif msg_type == "analysis_started" and content:
                prior_assistant_blob = content[:_MAX_MSG_CHARS]
            elif len(content) >= 120 and msg_type not in ("clarification", "out_of_scope", "unsupported"):
                prior_assistant_blob = content[:_MAX_MSG_CHARS]
        if prior_task_id and prior_assistant_blob:
            break

    return {
        "prior_task_id": prior_task_id,
        "prior_report_id": prior_report_id,
        "prior_assistant_blob": prior_assistant_blob,
        "recovered_intent": select_best_prior_analysis_intent(messages),
    }


class FollowUpService:
    def __init__(
        self,
        *,
        llm: LLMClient | None = None,
        llm_generate: LlmGenerateFn | None = None,
    ) -> None:
        self._llm = llm or llm_client
        self._llm_generate = llm_generate

    async def handle(
        self,
        *,
        query: str,
        intent: IntentUnderstandingResult | None,
        messages: list[Message],
        conversation_id: str | None = None,
        project_memory: Any | None = None,
        knowledge_notes_block: str | None = None,
    ) -> FollowUpResult:
        refs = extract_prior_refs(messages)
        prior_task_id = refs.get("prior_task_id")
        prior_report_id = refs.get("prior_report_id")
        has_prior = message_has_prior_artifact(messages)
        # Cross-session: ProjectMemory counts as prior even without local messages
        if project_memory is not None:
            try:
                ents = getattr(project_memory, "entities", None)
                findings = getattr(project_memory, "key_findings", None) or []
                if ents and (getattr(ents, "our_company", None) or findings):
                    has_prior = True
            except Exception:
                pass
        if knowledge_notes_block:
            has_prior = True

        if not has_prior:
            return FollowUpResult(
                upgrade_to_analysis=False,
                answer_markdown=(
                    "当前会话还没有可追问的上一轮分析或查询结果。"
                    "请先完成一轮竞品分析 / 信息收集 / 轻量查询，或明确说明要追问的对象。"
                ),
                follow_up_mode="no_prior",
                confidence=0.4,
                metadata={"conversation_id": conversation_id, "reason": "follow_up_no_prior"},
            )

        context_summary = self._build_context_summary(
            messages=messages,
            prior_task_id=prior_task_id,
            prior_report_id=prior_report_id,
            prior_assistant_blob=str(refs.get("prior_assistant_blob") or ""),
            intent=intent,
            recovered_intent=refs.get("recovered_intent"),
            project_memory=project_memory,
            knowledge_notes_block=knowledge_notes_block,
        )

        if self.should_upgrade(query):
            return FollowUpResult(
                upgrade_to_analysis=True,
                answer_markdown="",
                context_summary=context_summary[:2000],
                prior_task_id=prior_task_id,
                prior_report_id=prior_report_id,
                follow_up_mode="upgrade_analysis",
                confidence=0.8,
                metadata={
                    "conversation_id": conversation_id,
                    "upgrade_signal": True,
                },
            )

        answer = await self._short_answer(query=query, context_summary=context_summary)
        return FollowUpResult(
            upgrade_to_analysis=False,
            answer_markdown=answer,
            context_summary=context_summary[:500],
            prior_task_id=prior_task_id,
            prior_report_id=prior_report_id,
            follow_up_mode="short_answer",
            confidence=0.7,
            metadata={"conversation_id": conversation_id},
        )

    @staticmethod
    def should_upgrade(query: str) -> bool:
        return bool(_UPGRADE_PATTERN.search(query or ""))

    def _build_context_summary(
        self,
        *,
        messages: list[Message],
        prior_task_id: str | None,
        prior_report_id: str | None,
        prior_assistant_blob: str,
        intent: IntentUnderstandingResult | None,
        recovered_intent: dict[str, Any] | None,
        project_memory: Any | None = None,
        knowledge_notes_block: str | None = None,
    ) -> str:
        parts: list[str] = []
        # 1) Project Memory first (cross-session)
        if project_memory is not None:
            try:
                from app.domain.entities.project_memory import format_memory_prompt_block

                block = format_memory_prompt_block(project_memory)
                if block:
                    parts.append(block)
            except Exception:
                logger.exception("failed to format project memory for follow_up")

        # 2) Knowledge notes (user-authored; not public evidence)
        if knowledge_notes_block:
            parts.append(knowledge_notes_block.strip())

        entity = intent
        if recovered_intent and (not entity or not entity.company):
            try:
                entity = IntentUnderstandingResult.model_validate(recovered_intent)
            except Exception:
                entity = intent
        if entity and (entity.company or entity.product or entity.competitors):
            comps = "、".join(entity.competitors or [])
            parts.append(
                f"分析对象：{entity.company or '?'} vs {comps or '?'} / {entity.product or '?'}"
            )
        if prior_task_id:
            parts.append(f"上一轮 task_id：{prior_task_id}")
        if prior_report_id:
            parts.append(f"上一轮 report_id：{prior_report_id}")

        report_md = self._load_report_excerpt(prior_task_id, prior_report_id)
        if report_md:
            parts.append("## 上轮报告摘要\n" + report_md)

        collection_md = self._load_collection_excerpt(prior_task_id)
        if collection_md:
            parts.append("## 上轮收集摘要\n" + collection_md)

        if prior_assistant_blob:
            parts.append("## 上轮助手回复\n" + prior_assistant_blob)

        # Recent dialogue (truncated)
        recent_lines: list[str] = []
        for message in list(messages or [])[-_MAX_CONTEXT_MESSAGES:]:
            role = message.role
            content = (message.content or "").strip().replace("\n", " ")
            if not content:
                continue
            recent_lines.append(f"{role}: {content[:200]}")
        if recent_lines:
            parts.append("## 最近对话\n" + "\n".join(recent_lines))

        return "\n\n".join(parts).strip() or "（上下文为空）"

    @staticmethod
    def _load_report_excerpt(task_id: str | None, report_id: str | None) -> str:
        reports = task_report_runtime.get_reports()
        keys = [k for k in (report_id, task_id) if k]
        for key in keys:
            report = reports.get(str(key))
            if not isinstance(report, dict):
                continue
            md = report.get("markdown") or ""
            if not md and isinstance(report.get("formats"), dict):
                md = report["formats"].get("markdown") or ""
            if md:
                return str(md)[:_MAX_REPORT_CHARS]
        # Also scan by task_id field
        if task_id:
            for report in reports.values():
                if not isinstance(report, dict):
                    continue
                if str(report.get("task_id") or "") == str(task_id):
                    md = report.get("markdown") or ""
                    if md:
                        return str(md)[:_MAX_REPORT_CHARS]
        return ""

    @staticmethod
    def _load_collection_excerpt(task_id: str | None) -> str:
        if not task_id:
            return ""
        tasks = task_report_runtime.get_tasks()
        entry = tasks.get(str(task_id)) or {}
        state = entry.get("state") if isinstance(entry, dict) else None
        if not isinstance(state, dict):
            return ""
        # Collection may store markdown on report or final output
        for key in ("collection_markdown", "collection_output"):
            val = state.get(key)
            if isinstance(val, str) and val.strip():
                return val[:_MAX_REPORT_CHARS]
            if isinstance(val, dict):
                md = val.get("markdown") or val.get("summary") or ""
                if md:
                    return str(md)[:_MAX_REPORT_CHARS]
        evidence = state.get("evidence_bundle") or {}
        if isinstance(evidence, dict):
            items = evidence.get("evidence_items") or []
            lines = []
            for item in items[:8]:
                if isinstance(item, dict):
                    title = item.get("title") or ""
                    date = item.get("date") or ""
                    lines.append(f"- {title} ({date})")
            if lines:
                return "证据要点：\n" + "\n".join(lines)
        return ""

    async def _short_answer(self, *, query: str, context_summary: str) -> str:
        user_prompt = (
            f"## 上轮上下文\n{context_summary}\n\n"
            f"## 用户追问\n{query}\n\n"
            "请基于上下文作答。若上下文含「项目记忆 / 关键结论」，可引用但须标注"
            "「历史结论，需结合新问题」；上下文不足请明说。"
        )
        try:
            if self._llm_generate:
                resp = await self._llm_generate(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.3,
                )
            else:
                resp = await self._llm.generate(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.3,
                )
            content = (resp.content or "").strip()
            if content:
                return content
        except Exception as exc:
            logger.exception("follow_up short answer failed: %s", exc)
        return (
            "暂时无法基于上轮结果生成追问答复。请稍后重试，"
            "或改写为「请基于刚才内容出一份完整竞品分析报告」以启动完整分析。"
        )
