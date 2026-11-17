"""Build / patch a Research Task from Intent + routing, without launching workflows."""

from __future__ import annotations

import re
from typing import Any

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.report_dto import ReportCreateRequest
from app.application.dto.research_task_dto import (
    ConfirmResearchTaskRequest,
    FieldSource,
    ResearchTask,
    SourcedItem,
    SourcedText,
)
from app.application.dto.routing_dto import RoutingDecision
from app.application.services.intent_mapper import resolve_workflow_kind, to_report_create_request
from app.application.services.intent_understanding_service import _extract_companies_in_order
from app.infrastructure.persistence.copilot.stores import new_id

DEFAULT_RESEARCH_SCOPE = "近三年"
DEFAULT_COLLECTION_TOPICS_SUFFIX = "近期发展、产品能力和市场竞争表现"

_TIME_SCOPE_RE = re.compile(
    r"(近[0-9一二三四五六七八九十两]+年|近半年|近[0-9一二三两]+个?月|"
    r"最近[0-9一二三四五六七八九十两]+年|最近半年|"
    r"20[0-9]{2}\s*[-—至到]\s*20[0-9]{2}|"
    r"20[0-9]{2}年?|"
    r"近[期日]|最近)",
)


def _text_in_message(value: str | None, raw: str) -> bool:
    token = (value or "").strip()
    if not token:
        return False
    return token in (raw or "")


def _source_for_mentioned(value: str | None, raw: str, *, inferred: bool = False) -> FieldSource:
    if not (value or "").strip():
        return "unresolved"
    if _text_in_message(value, raw):
        return "user_input"
    return "system_inferred" if inferred or value else "user_input"


def _research_scope_from_message(raw: str) -> SourcedText:
    match = _TIME_SCOPE_RE.search(raw or "")
    if match:
        return SourcedText(value=match.group(0).strip(), source="user_input")
    return SourcedText(value=DEFAULT_RESEARCH_SCOPE, source="system_default")


def _collection_topics(
    intent: IntentUnderstandingResult,
    *,
    collection: bool,
) -> SourcedText:
    raw = intent.raw_message or ""
    product = (intent.product or "").strip()
    if collection and raw.strip():
        return SourcedText(value=raw.strip(), source="user_input")
    if product and _text_in_message(product, raw):
        return SourcedText(
            value=f"{product}{DEFAULT_COLLECTION_TOPICS_SUFFIX}",
            source="system_inferred",
        )
    if product:
        return SourcedText(
            value=f"{product}{DEFAULT_COLLECTION_TOPICS_SUFFIX}",
            source="system_inferred",
        )
    if raw.strip():
        return SourcedText(value=raw.strip(), source="user_input")
    return SourcedText(value=None, source="unresolved")


def _analysis_goal(intent: IntentUnderstandingResult) -> SourcedText:
    raw = (intent.raw_message or "").strip()
    objective = (intent.objective or "").strip()
    if raw:
        return SourcedText(value=raw, source="user_input")
    if objective and objective not in {
        "product_improvement",
        "intelligence_collection",
        "go_to_market",
        "investment_due_diligence",
        "competitive_defense",
        "positioning_switch",
        "partnership_evaluation",
        "feature_benchmark",
    }:
        return SourcedText(value=objective, source="user_input")
    if objective:
        return SourcedText(value=objective, source="system_default")
    return SourcedText(value=None, source="unresolved")


def _competitor_items(intent: IntentUnderstandingResult) -> list[SourcedItem]:
    raw = intent.raw_message or ""
    mentioned = set(_extract_companies_in_order(raw))
    items: list[SourcedItem] = []
    for name in intent.competitors or []:
        token = str(name or "").strip()
        if not token:
            continue
        source: FieldSource = "user_input" if token in mentioned or token in raw else "system_inferred"
        items.append(SourcedItem(value=token, source=source))
    return items


def build_research_task(
    *,
    intent: IntentUnderstandingResult,
    routing: RoutingDecision | None,
    conversation_id: str,
    project_id: str,
    source_message_id: str | None,
    analysis_mode: str = "fast",
    follow_up_upgrade: bool = False,
    follow_up_context: dict[str, Any] | None = None,
) -> ResearchTask:
    kind = "intelligence_collection"
    if routing and routing.legacy_workflow_kind:
        kind = routing.legacy_workflow_kind
    elif routing and routing.workflow_type == "research":
        kind = "intelligence_collection"
    elif routing and routing.workflow_type == "competitive_analysis":
        kind = "deep_analysis"
    else:
        kind = resolve_workflow_kind(intent)

    raw = intent.raw_message or ""
    company = (intent.company or "").strip() or None
    product = (intent.product or "").strip() or None
    company_source = _source_for_mentioned(company, raw, inferred=True) if company else "unresolved"
    product_in_text = bool(product and (product in raw or "酒店" in raw or "酒旅" in raw))
    product_source: FieldSource
    if not product:
        product_source = "unresolved"
    elif product_in_text:
        product_source = "user_input"
    else:
        product_source = "system_inferred"

    target = SourcedText(value=company, source=company_source)
    return ResearchTask(
        id=new_id(),
        status="pending",
        conversation_id=conversation_id,
        project_id=project_id,
        source_message_id=source_message_id,
        analysis_mode="full" if analysis_mode == "full" else "fast",
        routed_workflow=kind,  # type: ignore[arg-type]
        raw_message=raw,
        collection_targets=target,
        collection_topics=_collection_topics(intent, collection=kind == "intelligence_collection"),
        research_scope=_research_scope_from_message(raw),
        analysis_subject=target.model_copy(),
        competitors=_competitor_items(intent),
        analysis_product=SourcedText(value=product, source=product_source),
        analysis_goal=_analysis_goal(intent),
        follow_up_upgrade=follow_up_upgrade,
        follow_up_context=dict(follow_up_context or {}),
    )


def apply_confirmation_patch(
    task: ResearchTask,
    patch: ConfirmResearchTaskRequest | None,
) -> ResearchTask:
    if patch is None:
        return task
    data = task.model_copy(deep=True)
    if patch.collection_targets is not None:
        data.collection_targets = SourcedText(value=patch.collection_targets, source="user_input")
        if not data.analysis_subject.value:
            data.analysis_subject = data.collection_targets.model_copy()
    if patch.collection_topics is not None:
        data.collection_topics = SourcedText(value=patch.collection_topics, source="user_input")
    if patch.research_scope is not None:
        data.research_scope = SourcedText(value=patch.research_scope, source="user_input")
    if patch.analysis_subject is not None:
        data.analysis_subject = SourcedText(value=patch.analysis_subject, source="user_input")
        data.collection_targets = data.analysis_subject.model_copy()
    if patch.competitors is not None:
        data.competitors = [
            SourcedItem(value=name, source="user_input") for name in patch.competitors
        ]
    if patch.analysis_product is not None:
        data.analysis_product = SourcedText(value=patch.analysis_product, source="user_input")
    if patch.analysis_goal is not None:
        data.analysis_goal = SourcedText(value=patch.analysis_goal, source="user_input")
    if patch.analysis_mode is not None:
        data.analysis_mode = patch.analysis_mode
    return data


def intent_from_research_task(task: ResearchTask) -> IntentUnderstandingResult:
    company = task.analysis_subject.value or task.collection_targets.value
    product = task.analysis_product.value
    goal = task.analysis_goal.value
    raw = task.raw_message or goal or ""
    objective = goal
    if task.routed_workflow == "intelligence_collection":
        objective = "intelligence_collection"
    return IntentUnderstandingResult(
        type="competitive_analysis",
        company=company,
        competitors=task.competitor_names(),
        product=product,
        objective=objective,
        confidence=1.0,
        missing_fields=[],
        needs_clarification=False,
        clarification_question=None,
        raw_message=raw,
    )


def to_confirmed_report_request(task: ResearchTask) -> ReportCreateRequest:
    intent = intent_from_research_task(task)
    request = to_report_create_request(intent, analysis_mode=task.analysis_mode)
    optional = dict(request.optional or {})
    optional.update({
        "source": "research_task_confirmed",
        "research_task_confirmed": True,
        "research_task_id": task.id,
        "research_task": task.model_dump(),
        "research_scope": task.research_scope.value,
        "collection_topics": task.collection_topics.value,
        "collection_targets": task.collection_targets.value,
        "analysis_mode": task.analysis_mode,
        "workflow_kind": task.routed_workflow,
        "raw_message": task.raw_message,
        "competitors": task.competitor_names(),
    })
    scene = request.scene
    if task.analysis_goal.value:
        scene = task.analysis_goal.value
    if task.research_scope.value:
        extra = f"研究范围：{task.research_scope.value}"
        scene = f"{scene}\n{extra}".strip() if scene else extra
    if task.collection_topics.value and task.routed_workflow == "intelligence_collection":
        optional["dimensions"] = optional.get("dimensions") or []
        optional["skip_evidence_evaluation"] = True
        scene = task.collection_topics.value
        if task.research_scope.value:
            scene = f"{scene}\n研究范围：{task.research_scope.value}"
    return request.model_copy(
        update={
            "our_company": task.analysis_subject.value or request.our_company,
            "product": task.analysis_product.value or request.product,
            "scene": scene,
            "optional": optional,
        },
    )
