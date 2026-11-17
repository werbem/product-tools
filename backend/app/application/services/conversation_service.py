"""Conversation application service."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone
from typing import Any

from app.application.dto.conversation_dto import ConversationTurnResult, TurnStatus
from app.application.dto.conversation_event_dto import ConversationEvent
from app.application.dto.intent_dto import IntentUnderstandingRequest, IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext, RoutingDecision
from app.application.dto.workflow_launch_dto import WorkflowLaunchContext
from app.application.dto.research_task_dto import ConfirmResearchTaskRequest, ResearchTask
from app.application.exceptions import (
    ConversationNotFoundError,
    ProjectArchivedError,
    ProjectNotFoundError,
    ResearchTaskConflictError,
    ResearchTaskNotFoundError,
)
from app.application.services.intent_mapper import detect_analysis_intent, to_report_create_request
from app.application.services.research_task_builder import (
    apply_confirmation_patch,
    build_research_task,
    intent_from_research_task,
    to_confirmed_report_request,
)
from app.application.services.intent_understanding_service import (
    IntentUnderstandingService,
    _extract_peer_pair_from_text,
)
from app.application.services.intent_entities import (
    extract_listing_subject_company,
    infer_default_product,
    is_invalid_company_entity,
    is_same_brand_entity,
    looks_like_competitor_listing_query,
    resolve_competitor_suggestions,
    sanitize_company_name,
    sanitize_competitors,
)
from app.application.services.knowledge_service import KnowledgeService
from app.application.services.memory_writer import MemoryWriter
from app.application.services.project_service import ProjectService
from app.application.services.collection_workflow_launcher import CollectionWorkflowLauncher
from app.application.services.decision_routing import apply_decision_routing
from app.application.services.follow_up_service import (
    FollowUpService,
    merge_intent_for_upgrade,
    message_has_prior_artifact,
    select_best_prior_analysis_intent,
)
from app.application.services.router_service import RouterService
from app.application.services.simple_query_service import SimpleQueryService
from app.application.services.simple_question_service import SimpleQuestionService
from app.application.services.workflow_busy import BusyLongTask, busy_user_message, resolve_busy
from app.application.services.workflow_launcher import DeepAnalysisWorkflowLauncher
from app.domain.entities.conversation import Conversation
from app.domain.entities.copilot_common import utc_now
from app.domain.entities.knowledge_note import KnowledgeNote, format_knowledge_prompt_block
from app.domain.entities.message import Message
from app.domain.entities.project_memory import (
    ProjectMemory,
    format_memory_prompt_block,
    memory_to_optional_dict,
)
from app.infrastructure.events.conversation_event_bus import ConversationEventBus
from app.infrastructure.persistence.copilot.exceptions import NotFoundError as PersistenceNotFoundError
from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore
from app.infrastructure.persistence.copilot.stores import ConversationStore, MessageStore, new_id

_OUT_OF_SCOPE_REPLY = (
    "抱歉，该问题超出竞品分析助手的服务范围。"
    "我可以帮您做竞品分析报告，或收集竞品/产品的公开信息。"
)


class ConversationService:
    def __init__(
        self,
        conversation_store: ConversationStore,
        message_store: MessageStore,
        project_service: ProjectService,
        intent_service: IntentUnderstandingService,
        workflow_launcher: DeepAnalysisWorkflowLauncher | None = None,
        collection_launcher: CollectionWorkflowLauncher | None = None,
        event_bus: ConversationEventBus | None = None,
        router_service: RouterService | None = None,
        simple_query_service: SimpleQueryService | None = None,
        follow_up_service: FollowUpService | None = None,
        simple_question_service: SimpleQuestionService | None = None,
        memory_store: ProjectMemoryStore | None = None,
        knowledge_service: KnowledgeService | None = None,
    ) -> None:
        self._conversation_store = conversation_store
        self._message_store = message_store
        self._project_service = project_service
        self._intent_service = intent_service
        self._workflow_launcher = workflow_launcher
        self._collection_launcher = collection_launcher
        self._event_bus = event_bus
        self._router = router_service or RouterService()
        self._simple_query = simple_query_service or SimpleQueryService()
        self._follow_up = follow_up_service or FollowUpService()
        self._simple_question = simple_question_service or SimpleQuestionService(
            query_service=self._simple_query,
        )
        self._memory_store = memory_store or ProjectMemoryStore()
        self._memory_writer = MemoryWriter(store=self._memory_store)
        self._knowledge = knowledge_service or KnowledgeService()
        self._locks: dict[str, asyncio.Lock] = {}

    def _get_lock(self, conversation_id: str) -> asyncio.Lock:
        if conversation_id not in self._locks:
            self._locks[conversation_id] = asyncio.Lock()
        return self._locks[conversation_id]

    def create_conversation(
        self,
        project_id: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Conversation:
        self._project_service.get_project(project_id)
        now = utc_now()
        conversation = Conversation(
            id=new_id(),
            project_id=project_id,
            title=title,
            metadata=metadata or {},
            created_at=now,
            updated_at=now,
        )
        return self._conversation_store.create_conversation(conversation)

    def get_conversation(self, conversation_id: str) -> Conversation:
        conversation = self._conversation_store.get_conversation(conversation_id)
        if not conversation:
            raise ConversationNotFoundError(conversation_id)
        return conversation

    def list_conversations(self, project_id: str) -> list[Conversation]:
        self._project_service.get_project(project_id)
        return self._conversation_store.list_conversations_by_project(project_id)

    def get_messages(self, conversation_id: str) -> list[Message]:
        self.get_conversation(conversation_id)
        return self._message_store.list_messages_by_conversation(conversation_id)

    async def process_user_message(
        self,
        conversation_id: str,
        content: str,
        analysis_mode: str = "fast",
    ) -> ConversationTurnResult:
        async with self._get_lock(conversation_id):
            conversation = self.get_conversation(conversation_id)
            project = self._project_service.get_project(conversation.project_id)
            if project.status == "archived":
                raise ProjectArchivedError(conversation.project_id)

            self._cancel_pending_research_task(conversation)
            user_message = Message(
                id=new_id(),
                conversation_id=conversation_id,
                role="user",
                content=content,
            )
            self._message_store.append_message(user_message)
            # Immediate UX signal before Intent LLM (often 10–20s).
            await self._publish_turn_progress(
                conversation_id,
                phase="understanding_intent",
                stage_hint="正在识别意图…",
                progress=5,
            )

            partial = self._recover_partial(conversation_id)
            memory = self._load_project_memory(conversation.project_id)
            knowledge_notes = await self._retrieve_knowledge_notes(
                conversation.project_id, content,
            )
            knowledge_block = format_knowledge_prompt_block(knowledge_notes) or None
            partial = self._merge_memory_partial(partial, memory, raw_message=content)
            # Listing questions name the subject in-message — do not keep stale company
            # from prior clarification (e.g. 饿了么 leftover → 京东外卖问句).
            partial = self._apply_listing_subject_to_partial(partial, content)
            intent = await self._intent_service.understand(IntentUnderstandingRequest(
                message=content,
                partial=partial,
                conversation_id=conversation_id,
            ))
            # Fill any remaining empty entity slots from Memory after LLM
            intent = self._fill_intent_from_memory(intent, memory)
            intent = self._apply_listing_subject_to_intent(intent, content)
            # Drop pronouns / noise (「它都」from「它都有哪些竞品」) and restore prior brand
            intent = self._sanitize_intent_company(intent, memory, partial)
            intent = self._apply_suggested_competitors(
                intent, conversation_id, content, memory=memory,
            )

            status: TurnStatus
            task_id: str | None = None
            report_id: str | None = None
            assistant_content: str
            message_type: str
            routing_decision: RoutingDecision | None = None
            assistant_metadata: dict[str, Any] = {"intent": intent.model_dump()}

            if intent.needs_clarification:
                # Light query / follow_up /「有哪些竞品」must not be blocked by competitor clarification
                probe = self._router.route(
                    intent,
                    content,
                    self._build_routing_context(conversation, conversation_id),
                )
                if looks_like_competitor_listing_query(content):
                    from app.application.services.intent_mapper import detect_analysis_intent

                    if not detect_analysis_intent(content):
                        probe = RoutingDecision(
                            workflow_type="simple_question",
                            confidence=0.85,
                            reason="competitor_listing_bypass_clarification",
                            legacy_workflow_kind=None,
                        )
                if probe.workflow_type not in (
                    "information_query",
                    "follow_up",
                    "simple_question",
                ):
                    # Knowledge notes can answer without full CA entities
                    if knowledge_block:
                        routing_decision = RoutingDecision(
                            workflow_type="simple_question",
                            reason="knowledge_notes_bypass_clarification",
                            confidence=0.7,
                            legacy_workflow_kind=None,
                        )
                        assistant_metadata["routing_decision"] = (
                            routing_decision.to_metadata_dict()
                        )
                        wf = "simple_question"
                    else:
                        status = "needs_clarification"
                        message_type = "clarification"
                        assistant_content = intent.clarification_question or "请补充更多信息以便开始分析。"
                        assistant_metadata["message_type"] = message_type
                        assistant_metadata["understanding_summary"] = self._understanding_summary(
                            intent, "clarification", message_type,
                        )
                        assistant_message = Message(
                            id=new_id(),
                            conversation_id=conversation_id,
                            role="assistant",
                            content=assistant_content,
                            task_id=None,
                            metadata=assistant_metadata,
                        )
                        self._message_store.append_message(assistant_message)
                        if not conversation.title:
                            conversation.title = content[:40]
                        conversation.updated_at = utc_now()
                        try:
                            self._conversation_store.update_conversation(conversation)
                        except PersistenceNotFoundError:
                            pass
                        try:
                            self._project_service.touch_project(conversation.project_id)
                        except ProjectNotFoundError:
                            pass
                        return ConversationTurnResult(
                            conversation=conversation,
                            user_message=user_message,
                            assistant_message=assistant_message,
                            intent=intent,
                            status=status,
                            task_id=None,
                            report_id=None,
                            routing_decision=None,
                        )
                else:
                    routing_decision = probe
                    assistant_metadata["routing_decision"] = routing_decision.to_metadata_dict()
                    wf = routing_decision.workflow_type
            else:
                routing_decision = self._router.route(
                    intent,
                    content,
                    self._build_routing_context(conversation, conversation_id),
                )
                # Prefer answering from Knowledge Notes for brief "注意点" style Qs
                # even when Memory already filled entities (would otherwise LegacyBridge→Deep).
                if (
                    knowledge_block
                    and routing_decision.workflow_type in (
                        "competitive_analysis",
                        "research",
                    )
                    and self._router._looks_like_simple_question(content)
                ):
                    routing_decision = RoutingDecision(
                        workflow_type="simple_question",
                        confidence=0.78,
                        reason="knowledge_notes_prefer_simple_question",
                        legacy_workflow_kind=None,
                    )
                assistant_metadata["routing_decision"] = routing_decision.to_metadata_dict()
                wf = routing_decision.workflow_type

            # Phase 5: optional decision stack (off|shadow|on). Default off = legacy only.
            routing_ctx = self._build_routing_context(conversation, conversation_id)
            routing_decision, stack_meta, planner_clarify = apply_decision_routing(
                message=content,
                legacy_intent=intent,
                legacy_routing=routing_decision or RoutingDecision(
                    workflow_type="out_of_scope",
                    reason="missing_legacy_routing",
                    confidence=0.0,
                ),
                has_prior=bool(routing_ctx.has_prior_analysis),
                memory=memory,
                conversation_id=conversation_id,
                project_id=conversation.project_id,
                analysis_mode_hint=analysis_mode,
            )
            if stack_meta:
                assistant_metadata["decision_stack"] = stack_meta
            if planner_clarify:
                status = "needs_clarification"
                message_type = "clarification"
                assistant_content = planner_clarify
                assistant_metadata["routing_decision"] = routing_decision.to_metadata_dict()
                assistant_metadata["message_type"] = message_type
                assistant_metadata["understanding_summary"] = self._understanding_summary(
                    intent, "clarification", message_type,
                )
                assistant_message = Message(
                    id=new_id(),
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_content,
                    task_id=None,
                    metadata=assistant_metadata,
                )
                self._message_store.append_message(assistant_message)
                if not conversation.title:
                    conversation.title = content[:40]
                conversation.updated_at = utc_now()
                try:
                    self._conversation_store.update_conversation(conversation)
                except PersistenceNotFoundError:
                    pass
                try:
                    self._project_service.touch_project(conversation.project_id)
                except ProjectNotFoundError:
                    pass
                return ConversationTurnResult(
                    conversation=conversation,
                    user_message=user_message,
                    assistant_message=assistant_message,
                    intent=intent,
                    status=status,
                    task_id=None,
                    report_id=None,
                    routing_decision=routing_decision,
                )
            assistant_metadata["routing_decision"] = routing_decision.to_metadata_dict()
            wf = routing_decision.workflow_type

            if wf == "out_of_scope":
                status = "out_of_scope"
                message_type = "out_of_scope"
                # Keep legacy status alias for older clients via metadata
                assistant_metadata["legacy_status"] = "unsupported"
                assistant_content = _OUT_OF_SCOPE_REPLY
            elif wf == "information_query":
                query_result = await self._simple_query.answer(
                    query=content,
                    intent=intent,
                    conversation_id=conversation_id,
                    project_memory_block=format_memory_prompt_block(memory, limit=400) or None,
                    knowledge_notes_block=knowledge_block,
                )
                status = "query_answered"
                message_type = "query_answered"
                assistant_content = query_result.answer_markdown
                assistant_metadata.update({
                    "workflow_type": "information_query",
                    "workflow_kind": None,
                    "query_sources": [s.model_dump() for s in query_result.sources],
                    "query_confidence": query_result.confidence,
                    "query_metadata": query_result.metadata,
                })
            elif wf == "follow_up":
                msgs = self._message_store.list_messages_by_conversation(conversation_id)
                follow = await self._follow_up.handle(
                    query=content,
                    intent=intent,
                    messages=msgs,
                    conversation_id=conversation_id,
                    project_memory=memory,
                    knowledge_notes_block=knowledge_block,
                )
                if follow.follow_up_mode == "no_prior" or (
                    routing_decision and routing_decision.reason == "follow_up_no_prior"
                ):
                    status = "follow_up_answered"
                    message_type = "follow_up_answered"
                    assistant_content = follow.answer_markdown
                    assistant_metadata.update({
                        "workflow_type": "follow_up",
                        "follow_up_mode": "no_prior",
                        "prior_task_id": None,
                        "prior_report_id": None,
                    })
                elif follow.upgrade_to_analysis:
                    launcher = self._workflow_launcher
                    if not launcher:
                        raise RuntimeError("workflow launcher not configured")
                    busy = self._resolve_long_task_busy(conversation.project_id)
                    if busy:
                        status, message_type, assistant_content, busy_meta = (
                            self._workflow_busy_payload(busy)
                        )
                        assistant_metadata.update(busy_meta)
                        assistant_metadata.update({
                            "workflow_type": "follow_up",
                            "follow_up_mode": "upgrade_blocked_busy",
                            "prior_task_id": follow.prior_task_id,
                            "prior_report_id": follow.prior_report_id,
                        })
                    else:
                        try:
                            launch_intent = self._intent_for_follow_up_upgrade(
                                intent, msgs, project_memory=memory,
                            )
                            report_request = to_report_create_request(
                                launch_intent, analysis_mode=analysis_mode,
                            )
                        except ValueError as exc:
                            status = "follow_up_answered"
                            message_type = "follow_up_answered"
                            assistant_content = (
                                "想升级为完整竞品分析，但还缺少必要信息。\n"
                                "请补充：分析公司、对比竞品、以及产品或场景。\n"
                                "例如：飞猪 vs 美团，产品是酒店。"
                            )
                            assistant_metadata.update({
                                "workflow_type": "follow_up",
                                "follow_up_mode": "upgrade_blocked_missing_entities",
                                "prior_task_id": follow.prior_task_id,
                                "prior_report_id": follow.prior_report_id,
                                "upgrade_error": str(exc),
                            })
                        else:
                            pending = self._stage_research_task(
                                conversation=conversation,
                                user_message_id=user_message.id,
                                intent=launch_intent,
                                routing=RoutingDecision(
                                    workflow_type="competitive_analysis",
                                    reason="follow_up_upgrade",
                                    confidence=0.9,
                                    legacy_workflow_kind="deep_analysis",
                                ),
                                analysis_mode=analysis_mode,
                                follow_up_upgrade=True,
                                follow_up_context={
                                    "query": content,
                                    "context_summary": follow.context_summary,
                                    "prior_task_id": follow.prior_task_id,
                                    "prior_report_id": follow.prior_report_id,
                                },
                            )
                            status = "awaiting_confirmation"
                            message_type = "research_task_confirmation"
                            assistant_content = self._research_task_confirmation_message(pending)
                            assistant_metadata.update({
                                "workflow_type": "deep_analysis",
                                "workflow_kind": "deep_analysis",
                                "analysis_mode": analysis_mode,
                                "follow_up_mode": "upgrade_awaiting_confirmation",
                                "prior_task_id": follow.prior_task_id,
                                "prior_report_id": follow.prior_report_id,
                                "research_task": pending.model_dump(),
                            })
                else:
                    status = "follow_up_answered"
                    message_type = "follow_up_answered"
                    assistant_content = follow.answer_markdown
                    assistant_metadata.update({
                        "workflow_type": "follow_up",
                        "follow_up_mode": "short_answer",
                        "prior_task_id": follow.prior_task_id,
                        "prior_report_id": follow.prior_report_id,
                    })
            elif wf == "simple_question":
                suggested_pack = None
                if looks_like_competitor_listing_query(content):
                    suggested_pack = resolve_competitor_suggestions(
                        intent.company,
                        intent.product,
                        memory,
                        intent_competitors=list(intent.competitors or []),
                    )
                suggested = list((suggested_pack or {}).get("peers") or [])
                if looks_like_competitor_listing_query(content):
                    # Always answer listing locally — never fall through to
                    # SimpleQuestion LLM/search (40s timeout → UI ISE).
                    company = intent.company or "该公司"
                    product = (
                        intent.product
                        or infer_default_product(company)
                        or "相关业务"
                    )
                    if suggested:
                        names = "、".join(suggested)
                        mode = str(
                            (suggested_pack or {}).get("question_mode") or "curated_peers"
                        )
                        # Curated / memory peers: names only (user asked who the peers are)
                        assistant_content = names
                        intent = intent.model_copy(
                            update={
                                "competitors": suggested,
                                "product": intent.product or infer_default_product(company),
                                "needs_clarification": False,
                                "missing_fields": [
                                    f for f in (intent.missing_fields or [])
                                    if f not in ("competitors", "product")
                                ],
                                "clarification_question": None,
                            },
                        )
                        # Persist into Memory so next listing/analysis in this
                        # project hits peer graph (no web). Prefer curated tag
                        # when any curated peer was used; else user/intent.
                        try:
                            sources = list(
                                (suggested_pack or {}).get("sources") or []
                            )
                            peer_source = (
                                "curated"
                                if "curated" in sources or mode == "curated_peers"
                                else "user"
                            )
                            self._memory_writer.record_peer_relations(
                                project_id=conversation.project_id,
                                company=intent.company,
                                competitors=suggested,
                                product=intent.product,
                                source_task_id=None,
                                source_type=peer_source,  # type: ignore[arg-type]
                            )
                        except Exception:
                            pass
                        confidence = (
                            0.85
                            if mode.startswith("memory") or mode == "mixed_peers"
                            else 0.8
                        )
                        q_meta = {
                            "source": mode,
                            "skipped_light_search": True,
                            "persisted_to_memory": True,
                            "peer_source_breakdown": {
                                "memory": list(
                                    (suggested_pack or {}).get("memory_peers") or []
                                ),
                                "curated": list(
                                    (suggested_pack or {}).get("curated_peers") or []
                                ),
                                "intent": list(
                                    (suggested_pack or {}).get("intent_peers") or []
                                ),
                                "sources": list(
                                    (suggested_pack or {}).get("sources") or []
                                ),
                            },
                        }
                    else:
                        mode = "listing_guide"
                        assistant_content = (
                            f"目前还没有为**{company}**整理好的常见竞品名单。"
                            "请直接告诉我对标公司（例如：淘宝、京东、抖音电商），"
                            "或回复「帮我做竞品分析」并列出对比对象。"
                        )
                        confidence = 0.55
                        q_meta = {
                            "source": mode,
                            "skipped_light_search": True,
                            "empty_peers": True,
                        }
                    status = "question_answered"
                    message_type = "question_answered"
                    assistant_metadata["intent"] = intent.model_dump()
                    if suggested:
                        assistant_metadata["suggested_competitors"] = suggested
                    assistant_metadata.update({
                        "workflow_type": "simple_question",
                        "workflow_kind": None,
                        "question_mode": mode,
                        "query_sources": [],
                        "question_confidence": confidence,
                        "question_metadata": q_meta,
                    })
                else:
                    msgs = self._message_store.list_messages_by_conversation(conversation_id)
                    q = await self._simple_question.answer(
                        query=content,
                        intent=intent,
                        messages=msgs,
                        conversation_id=conversation_id,
                        project_memory_block=format_memory_prompt_block(memory, limit=400) or None,
                        knowledge_notes_block=knowledge_block,
                    )
                    status = "question_answered"
                    message_type = "question_answered"
                    assistant_content = q.answer_markdown
                    assistant_metadata.update({
                        "workflow_type": "simple_question",
                        "workflow_kind": None,
                        "question_mode": q.question_mode,
                        "query_sources": [s.model_dump() for s in q.sources],
                        "question_confidence": q.confidence,
                        "question_metadata": q.metadata,
                    })
            elif wf == "research":
                launcher = self._collection_launcher
                if not launcher:
                    raise RuntimeError("collection launcher not configured")
                busy = self._resolve_long_task_busy(conversation.project_id)
                if busy:
                    status, message_type, assistant_content, busy_meta = (
                        self._workflow_busy_payload(busy)
                    )
                    assistant_metadata.update(busy_meta)
                else:
                    pending = self._stage_research_task(
                        conversation=conversation,
                        user_message_id=user_message.id,
                        intent=intent,
                        routing=routing_decision,
                        analysis_mode=analysis_mode,
                    )
                    status = "awaiting_confirmation"
                    message_type = "research_task_confirmation"
                    assistant_content = self._research_task_confirmation_message(pending)
                    assistant_metadata.update({
                        "workflow_type": "intelligence_collection",
                        "workflow_kind": "intelligence_collection",
                        "analysis_mode": analysis_mode,
                        "research_task": pending.model_dump(),
                    })
            elif wf == "competitive_analysis":
                launcher = self._workflow_launcher
                if not launcher:
                    raise RuntimeError("workflow launcher not configured")
                busy = self._resolve_long_task_busy(conversation.project_id)
                if busy:
                    status, message_type, assistant_content, busy_meta = (
                        self._workflow_busy_payload(busy)
                    )
                    assistant_metadata.update(busy_meta)
                else:
                    pending = self._stage_research_task(
                        conversation=conversation,
                        user_message_id=user_message.id,
                        intent=intent,
                        routing=routing_decision,
                        analysis_mode=analysis_mode,
                    )
                    status = "awaiting_confirmation"
                    message_type = "research_task_confirmation"
                    assistant_content = self._research_task_confirmation_message(pending)
                    assistant_metadata.update({
                        "workflow_type": "deep_analysis",
                        "workflow_kind": "deep_analysis",
                        "analysis_mode": analysis_mode,
                        "research_task": pending.model_dump(),
                    })
            else:
                status = "out_of_scope"
                message_type = "out_of_scope"
                assistant_content = _OUT_OF_SCOPE_REPLY

            assistant_metadata["message_type"] = message_type
            assistant_metadata["understanding_summary"] = self._understanding_summary(
                intent, wf, message_type,
            )
            assistant_message = Message(
                id=new_id(),
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                task_id=task_id,
                metadata=assistant_metadata,
            )
            self._message_store.append_message(assistant_message)

            if not conversation.title:
                conversation.title = content[:40]
            conversation.updated_at = utc_now()
            try:
                self._conversation_store.update_conversation(conversation)
            except PersistenceNotFoundError:
                # Project/conversation may have been deleted while intent/workflow ran.
                pass
            try:
                self._project_service.touch_project(conversation.project_id)
            except ProjectNotFoundError:
                pass

            return ConversationTurnResult(
                conversation=conversation,
                user_message=user_message,
                assistant_message=assistant_message,
                intent=intent,
                status=status,
                task_id=task_id,
                report_id=report_id,
                routing_decision=routing_decision,
            )

    async def confirm_research_task(
        self,
        conversation_id: str,
        research_task_id: str,
        patch: ConfirmResearchTaskRequest | None = None,
    ) -> ConversationTurnResult:
        async with self._get_lock(conversation_id):
            conversation = self.get_conversation(conversation_id)
            project = self._project_service.get_project(conversation.project_id)
            if project.status == "archived":
                raise ProjectArchivedError(conversation.project_id)

            pending_raw = dict((conversation.metadata or {}).get("pending_research_task") or {})
            if not pending_raw or pending_raw.get("id") != research_task_id:
                raise ResearchTaskNotFoundError(research_task_id)
            pending = ResearchTask.model_validate(pending_raw)

            if pending.status == "confirmed" and pending.launched_task_id:
                return self._replay_confirmed_turn(conversation, pending)

            if pending.status != "pending":
                raise ResearchTaskConflictError(research_task_id)

            pending = apply_confirmation_patch(pending, patch)
            if not pending.analysis_subject.value and not pending.collection_targets.value:
                raise ResearchTaskConflictError("analysis_subject is required")
            if pending.routed_workflow == "deep_analysis" and not pending.competitor_names():
                raise ResearchTaskConflictError("competitors are required")
            if not pending.analysis_product.value and pending.routed_workflow == "deep_analysis":
                raise ResearchTaskConflictError("analysis_product is required")

            busy = self._resolve_long_task_busy(conversation.project_id)
            if busy:
                status, message_type, assistant_content, busy_meta = self._workflow_busy_payload(busy)
                assistant_message = Message(
                    id=new_id(),
                    conversation_id=conversation_id,
                    role="assistant",
                    content=assistant_content,
                    metadata={**busy_meta, "message_type": message_type, "research_task": pending.model_dump()},
                )
                self._message_store.append_message(assistant_message)
                return ConversationTurnResult(
                    conversation=conversation,
                    user_message=self._latest_user_message(conversation_id),
                    assistant_message=assistant_message,
                    intent=intent_from_research_task(pending),
                    status="workflow_busy",
                    routing_decision=None,
                )

            report_request = to_confirmed_report_request(pending)
            memory = self._load_project_memory(conversation.project_id)
            knowledge_notes = await self._retrieve_knowledge_notes(
                conversation.project_id,
                pending.analysis_goal.value or pending.raw_message,
            )
            report_request = self._attach_memory_optional(report_request, memory)
            report_request = self._attach_knowledge_optional(report_request, knowledge_notes)
            if pending.follow_up_upgrade:
                ctx = pending.follow_up_context or {}
                scene_extra = (
                    f"{report_request.scene or ''}\n"
                    f"【追问升级】{ctx.get('query') or ''}\n"
                    f"【上轮上下文摘要】\n{ctx.get('context_summary') or ''}"
                ).strip()
                optional = dict(report_request.optional or {})
                optional.update({
                    "follow_up": True,
                    "prior_task_id": ctx.get("prior_task_id"),
                    "prior_report_id": ctx.get("prior_report_id"),
                    "follow_up_context": str(ctx.get("context_summary") or "")[:2000],
                })
                report_request = report_request.model_copy(
                    update={"scene": scene_extra[:2500], "optional": optional},
                )

            if pending.routed_workflow == "intelligence_collection":
                launcher = self._collection_launcher
                if not launcher:
                    raise RuntimeError("collection launcher not configured")
            else:
                launcher = self._workflow_launcher
                if not launcher:
                    raise RuntimeError("workflow launcher not configured")

            launch_intent = intent_from_research_task(pending)
            routing_decision = RoutingDecision(
                workflow_type=(
                    "research"
                    if pending.routed_workflow == "intelligence_collection"
                    else "competitive_analysis"
                ),
                reason="research_task_confirmed",
                confidence=1.0,
                legacy_workflow_kind=pending.routed_workflow,
            )
            launch_result = await launcher.launch(
                report_request,
                WorkflowLaunchContext(
                    project_id=conversation.project_id,
                    conversation_id=conversation_id,
                    source_message_id=pending.source_message_id,
                ),
            )
            pending = pending.model_copy(update={
                "status": "confirmed",
                "launched_task_id": launch_result.task_id,
                "launched_report_id": launch_result.report_id,
            })
            meta = dict(conversation.metadata or {})
            meta["pending_research_task"] = pending.model_dump()
            meta["last_confirmed_research_task"] = pending.model_dump()
            conversation.metadata = meta
            conversation.updated_at = utc_now()
            try:
                self._conversation_store.update_conversation(conversation)
            except PersistenceNotFoundError:
                pass

            if pending.routed_workflow == "deep_analysis":
                try:
                    self._memory_writer.record_peer_relations(
                        project_id=conversation.project_id,
                        company=launch_intent.company,
                        competitors=list(launch_intent.competitors or []),
                        product=launch_intent.product,
                        source_task_id=launch_result.task_id,
                        source_type="user",
                    )
                except Exception:
                    pass

            mode_label = "完整模式" if pending.analysis_mode == "full" else "快速模式"
            if pending.routed_workflow == "intelligence_collection":
                assistant_content = self._collection_started_message(launch_intent, mode_label)
                workflow_type = "intelligence_collection"
            else:
                if pending.follow_up_upgrade:
                    assistant_content = (
                        "已基于上一轮结果启动完整竞品分析（追问升级）。\n"
                        f"分析模式：{mode_label}\n正在启动分析，请稍候…"
                    )
                else:
                    assistant_content = self._analysis_started_message(launch_intent, mode_label)
                workflow_type = "deep_analysis"

            assistant_metadata: dict[str, Any] = {
                "intent": launch_intent.model_dump(),
                "message_type": "analysis_started",
                "task_id": launch_result.task_id,
                "report_id": launch_result.report_id,
                "workflow_type": workflow_type,
                "workflow_kind": pending.routed_workflow,
                "analysis_mode": pending.analysis_mode,
                "research_task": pending.model_dump(),
                "routing_decision": routing_decision.to_metadata_dict(),
                "routing_debug": (report_request.optional or {}).get("routing_debug"),
                "validated_input": self._validated_input_snapshot(report_request, launch_intent),
            }
            if pending.follow_up_upgrade:
                assistant_metadata["follow_up_mode"] = "upgrade_analysis"
                assistant_metadata["prior_task_id"] = pending.follow_up_context.get("prior_task_id")
                assistant_metadata["prior_report_id"] = pending.follow_up_context.get("prior_report_id")

            assistant_message = Message(
                id=new_id(),
                conversation_id=conversation_id,
                role="assistant",
                content=assistant_content,
                task_id=launch_result.task_id,
                metadata=assistant_metadata,
            )
            pending = pending.model_copy(update={"confirmation_message_id": assistant_message.id})
            meta["pending_research_task"] = pending.model_dump()
            meta["last_confirmed_research_task"] = pending.model_dump()
            conversation.metadata = meta
            try:
                self._conversation_store.update_conversation(conversation)
            except PersistenceNotFoundError:
                pass
            self._message_store.append_message(assistant_message)
            await self._publish_analysis_started(
                conversation_id, launch_result.task_id, launch_result.report_id,
            )
            try:
                self._project_service.touch_project(conversation.project_id)
            except ProjectNotFoundError:
                pass
            return ConversationTurnResult(
                conversation=conversation,
                user_message=self._latest_user_message(conversation_id),
                assistant_message=assistant_message,
                intent=launch_intent,
                status="analysis_started",
                task_id=launch_result.task_id,
                report_id=launch_result.report_id,
                routing_decision=routing_decision,
            )

    def _stage_research_task(
        self,
        *,
        conversation: Conversation,
        user_message_id: str,
        intent: IntentUnderstandingResult,
        routing: RoutingDecision | None,
        analysis_mode: str,
        follow_up_upgrade: bool = False,
        follow_up_context: dict[str, Any] | None = None,
    ) -> ResearchTask:
        pending = build_research_task(
            intent=intent,
            routing=routing,
            conversation_id=conversation.id,
            project_id=conversation.project_id,
            source_message_id=user_message_id,
            analysis_mode=analysis_mode,
            follow_up_upgrade=follow_up_upgrade,
            follow_up_context=follow_up_context,
        )
        meta = dict(conversation.metadata or {})
        meta["pending_research_task"] = pending.model_dump()
        conversation.metadata = meta
        conversation.updated_at = utc_now()
        try:
            self._conversation_store.update_conversation(conversation)
        except PersistenceNotFoundError:
            pass
        return pending

    def _cancel_pending_research_task(self, conversation: Conversation) -> None:
        meta = dict(conversation.metadata or {})
        pending = meta.get("pending_research_task")
        if not isinstance(pending, dict) or pending.get("status") != "pending":
            return
        pending = dict(pending)
        pending["status"] = "cancelled"
        meta["pending_research_task"] = pending
        conversation.metadata = meta
        conversation.updated_at = utc_now()
        try:
            self._conversation_store.update_conversation(conversation)
        except PersistenceNotFoundError:
            pass

    def _latest_user_message(self, conversation_id: str) -> Message:
        messages = self._message_store.list_messages_by_conversation(conversation_id)
        for message in reversed(messages):
            if message.role == "user":
                return message
        raise ConversationNotFoundError(conversation_id)

    def _replay_confirmed_turn(
        self,
        conversation: Conversation,
        pending: ResearchTask,
    ) -> ConversationTurnResult:
        messages = self._message_store.list_messages_by_conversation(conversation.id)
        assistant = None
        if pending.confirmation_message_id:
            assistant = next(
                (m for m in messages if m.id == pending.confirmation_message_id),
                None,
            )
        if assistant is None:
            assistant = next(
                (
                    m
                    for m in reversed(messages)
                    if (m.metadata or {}).get("research_task", {}).get("id") == pending.id
                    and (m.metadata or {}).get("message_type") == "analysis_started"
                ),
                None,
            )
        if assistant is None:
            assistant = Message(
                id=new_id(),
                conversation_id=conversation.id,
                role="assistant",
                content="任务已确认并启动。",
                task_id=pending.launched_task_id,
                metadata={
                    "message_type": "analysis_started",
                    "research_task": pending.model_dump(),
                    "task_id": pending.launched_task_id,
                    "report_id": pending.launched_report_id,
                },
            )
        return ConversationTurnResult(
            conversation=conversation,
            user_message=self._latest_user_message(conversation.id),
            assistant_message=assistant,
            intent=intent_from_research_task(pending),
            status="analysis_started",
            task_id=pending.launched_task_id,
            report_id=pending.launched_report_id,
            routing_decision=RoutingDecision(
                workflow_type=(
                    "research"
                    if pending.routed_workflow == "intelligence_collection"
                    else "competitive_analysis"
                ),
                reason="research_task_already_confirmed",
                confidence=1.0,
                legacy_workflow_kind=pending.routed_workflow,
            ),
        )

    @staticmethod
    def _research_task_confirmation_message(task: ResearchTask) -> str:
        subject = task.analysis_subject.value or task.collection_targets.value or "未指定"
        peers = "、".join(task.competitor_names()) or "（待补充）"
        product = task.analysis_product.value or "未指定"
        scope = task.research_scope.value or "未指定"
        kind = "信息收集" if task.routed_workflow == "intelligence_collection" else "竞品分析"
        return (
            f"已解析研究任务，请确认后开始{kind}。\n"
            f"分析对象：{subject}\n"
            f"竞品对象：{peers}\n"
            f"分析产品：{product}\n"
            f"研究范围：{scope}"
        )

    def _resolve_long_task_busy(self, project_id: str) -> BusyLongTask | None:
        """Single-worker gate: any incomplete Deep/Collection blocks a new launch.

        Scope is **global** (not project-scoped). project_id is retained for
        logging / future multi-tenant; under one uvicorn worker, global is safer
        because Intent/Research share the same LLM client.
        """
        return resolve_busy(
            deep_launcher=self._workflow_launcher,
            collection_launcher=self._collection_launcher,
            project_id=project_id,
        )

    @staticmethod
    def _workflow_busy_payload(
        busy: BusyLongTask,
    ) -> tuple[str, str, str, dict[str, Any]]:
        """status, message_type, content, metadata — never analysis_started."""
        return (
            "workflow_busy",
            "workflow_busy",
            busy_user_message(busy),
            {
                "busy_task_id": busy.task_id,
                "busy_workflow_kind": busy.workflow_kind,
                "busy_status": busy.status,
                "workflow_type": None,
                "workflow_kind": None,
            },
        )

    def _build_routing_context(
        self,
        conversation: Conversation,
        conversation_id: str,
    ) -> ConversationRoutingContext:
        msgs = self._message_store.list_messages_by_conversation(conversation_id)
        memory = self._load_project_memory(conversation.project_id)
        has_memory = bool(
            memory
            and (
                memory.entities.our_company
                or memory.key_findings
                or memory.last_task_id
            )
        )
        return ConversationRoutingContext(
            conversation_id=conversation_id,
            project_id=conversation.project_id,
            has_prior_analysis=message_has_prior_artifact(msgs) or has_memory,
            metadata={"has_project_memory": has_memory},
        )

    def _load_project_memory(self, project_id: str) -> ProjectMemory | None:
        try:
            return self._memory_store.get(project_id)
        except Exception:
            return None

    async def _retrieve_knowledge_notes(
        self,
        project_id: str,
        query: str,
    ) -> list[KnowledgeNote]:
        try:
            return await self._knowledge.retrieve_for_prompt_async(project_id, query)
        except Exception:
            return []

    @staticmethod
    def _sanitize_intent_company(
        intent: IntentUnderstandingResult,
        memory: ProjectMemory | None,
        partial: IntentUnderstandingResult | None,
    ) -> IntentUnderstandingResult:
        """Reject pronoun/noise company; fall back to partial → Memory → product brand."""
        company = sanitize_company_name(intent.company)
        if company:
            if company == intent.company:
                return intent
            return intent.model_copy(update={"company": company})
        for candidate in (
            sanitize_company_name(partial.company if partial else None),
            sanitize_company_name(memory.entities.our_company if memory else None),
            sanitize_company_name(intent.product),
            sanitize_company_name(partial.product if partial else None),
            sanitize_company_name(memory.entities.product if memory else None),
        ):
            if candidate:
                return intent.model_copy(update={"company": candidate})
        if intent.company and is_invalid_company_entity(intent.company):
            return intent.model_copy(update={"company": None})
        return intent

    @staticmethod
    def _merge_memory_partial(
        partial: IntentUnderstandingResult | None,
        memory: ProjectMemory | None,
        *,
        raw_message: str,
    ) -> IntentUnderstandingResult | None:
        """Clarification partial wins non-empty; Memory fills empty slots only.

        When the current message explicitly names an A-vs-B pair, do not inject
        Memory competitors / last objective — those belong to a prior analysis.
        """
        if not memory:
            return partial
        ents = memory.entities
        mem_company = sanitize_company_name(ents.our_company)
        if not (mem_company or ents.product or ents.competitors):
            return partial

        peer_a, peer_b = _extract_peer_pair_from_text(raw_message or "")
        explicit_peer_pair = bool(peer_a and peer_b)

        if partial is None:
            if explicit_peer_pair:
                return IntentUnderstandingResult(
                    type="competitive_analysis",
                    company=sanitize_company_name(peer_a) or peer_a,
                    competitors=[peer_b],
                    product=ents.product,
                    objective=None,
                    confidence=0.7,
                    needs_clarification=False,
                    raw_message=raw_message,
                )
            return IntentUnderstandingResult(
                type="competitive_analysis",
                company=mem_company,
                competitors=list(ents.competitors),
                product=ents.product,
                objective=memory.last_objectives[0] if memory.last_objectives else None,
                confidence=0.7,
                needs_clarification=False,
                raw_message=raw_message,
            )
        partial_company = sanitize_company_name(partial.company)
        if explicit_peer_pair:
            return IntentUnderstandingResult(
                type=partial.type,
                company=partial_company or sanitize_company_name(peer_a) or peer_a or mem_company,
                # Current-message A/B wins over recovered clarification / Memory peers.
                competitors=[peer_b],
                product=partial.product or ents.product,
                # Do not inject memory.last_objectives for a new A-vs-B ask.
                objective=partial.objective,
                confidence=max(float(partial.confidence or 0.5), 0.7),
                needs_clarification=partial.needs_clarification,
                clarification_question=partial.clarification_question,
                missing_fields=list(partial.missing_fields or []),
                raw_message=partial.raw_message or raw_message,
            )
        return IntentUnderstandingResult(
            type=partial.type,
            company=partial_company or mem_company,
            competitors=list(partial.competitors or ents.competitors or []),
            product=partial.product or ents.product,
            objective=partial.objective or (
                memory.last_objectives[0] if memory.last_objectives else None
            ),
            confidence=max(float(partial.confidence or 0.5), 0.7),
            needs_clarification=partial.needs_clarification,
            clarification_question=partial.clarification_question,
            missing_fields=list(partial.missing_fields or []),
            raw_message=partial.raw_message or raw_message,
        )

    @staticmethod
    def _fill_intent_from_memory(
        intent: IntentUnderstandingResult,
        memory: ProjectMemory | None,
    ) -> IntentUnderstandingResult:
        if not memory:
            return intent
        ents = memory.entities
        peer_a, peer_b = _extract_peer_pair_from_text(intent.raw_message or "")
        explicit_peer_pair = bool(peer_a and peer_b)

        company = sanitize_company_name(intent.company) or sanitize_company_name(
            ents.our_company,
        )
        product = intent.product or ents.product
        if explicit_peer_pair:
            # Keep message-derived peers; never backfill Memory competitors.
            company = sanitize_company_name(intent.company) or sanitize_company_name(peer_a) or peer_a
            competitors = sanitize_competitors(
                list(intent.competitors or []) or ([peer_b] if peer_b else []),
                company,
            )
        else:
            competitors = list(intent.competitors or []) or list(ents.competitors or [])
            competitors = sanitize_competitors(competitors, company)
        if (
            company == intent.company
            and product == intent.product
            and competitors == list(intent.competitors or [])
        ):
            return intent
        # Recompute clarification lightly when Memory filled gaps
        missing: list[str] = []
        if not company:
            missing.append("company")
        if not competitors and not looks_like_competitor_listing_query(intent.raw_message):
            missing.append("competitors")
        if not product:
            missing.append("product")
        needs = bool(missing) and intent.type == "competitive_analysis"
        clarification = intent.clarification_question
        if needs and not clarification:
            if "competitors" in missing:
                clarification = "请告诉我主要对比哪些竞品？"
            elif "company" in missing:
                clarification = "请告诉我您要分析哪家公司（分析公司）？"
            elif "product" in missing:
                clarification = "请告诉我要分析的具体产品或市场是什么？"
        return intent.model_copy(
            update={
                "company": company,
                "product": product,
                "competitors": competitors,
                "missing_fields": missing if needs else [],
                "needs_clarification": needs,
                "clarification_question": clarification if needs else None,
            },
        )

    def _apply_suggested_competitors(
        self,
        intent: IntentUnderstandingResult,
        conversation_id: str,
        content: str,
        memory: ProjectMemory | None = None,
    ) -> IntentUnderstandingResult:
        """Fill peers for deep analysis: conversation suggestions → Memory/edges ∪ curated.

        Single-entity asks (「分析携程酒店竞争优势并给策略建议」) should auto-launch when
        peers can be resolved; only clarify when the peer graph/curated set is empty.
        """
        if intent.type != "competitive_analysis":
            return intent
        accepting = (
            detect_analysis_intent(content) or "用这些竞品" in (content or "")
        )
        comps = sanitize_competitors(list(intent.competitors or []), intent.company)
        if not comps:
            comps = self._recover_suggested_competitors(conversation_id)
        if not comps and accepting and intent.company:
            product_hint = intent.product or infer_default_product(intent.company)
            pack = resolve_competitor_suggestions(
                intent.company,
                product_hint,
                memory,
                intent_competitors=list(intent.competitors or []),
            )
            comps = list(pack.get("peers") or [])
        if not comps:
            # No peers available — keep Intent's clarification (or ask if analysis launch)
            if not accepting:
                return intent
            missing = list(intent.missing_fields or [])
            if "competitors" not in missing:
                missing.append("competitors")
            return intent.model_copy(
                update={
                    "competitors": [],
                    "missing_fields": missing,
                    "needs_clarification": True,
                    "clarification_question": (
                        intent.clarification_question
                        or "请告诉我主要对比哪些竞品？"
                    ),
                },
            )
        # Already have peers but not launching yet — keep sanitized comps only
        if not accepting:
            if comps != list(intent.competitors or []):
                return intent.model_copy(update={"competitors": comps})
            return intent
        product = intent.product or infer_default_product(intent.company)
        if product and intent.company and is_same_brand_entity(product, intent.company):
            product = infer_default_product(intent.company) or product
        missing = [
            f for f in (intent.missing_fields or [])
            if f not in ("competitors", "product")
        ]
        if not intent.company:
            missing.append("company")
        if not product:
            missing.append("product")
        needs = bool(missing)
        update: dict[str, Any] = {
            "competitors": comps,
            "product": product,
            "missing_fields": missing,
            "needs_clarification": needs,
            "clarification_question": None if not needs else intent.clarification_question,
        }
        return intent.model_copy(update=update)

    @staticmethod
    def _apply_listing_subject_to_partial(
        partial: IntentUnderstandingResult | None,
        content: str,
    ) -> IntentUnderstandingResult | None:
        subject = extract_listing_subject_company(content)
        if not subject:
            return partial
        product = None
        if "外卖" in subject or "外卖" in (content or ""):
            product = "外卖"
        elif "酒店" in subject or "酒店" in (content or ""):
            product = "酒店"
        if partial is None:
            return IntentUnderstandingResult(
                type="competitive_analysis",
                company=subject,
                competitors=[],
                product=product,
                confidence=0.75,
                needs_clarification=False,
                missing_fields=[],
                raw_message=content,
            )
        update: dict[str, Any] = {
            "company": subject,
            "raw_message": content,
            "needs_clarification": False,
            "clarification_question": None,
            "missing_fields": [
                f for f in (partial.missing_fields or []) if f != "competitors"
            ],
        }
        # Reset peers / stale product when subject brand changes
        if partial.company and partial.company != subject:
            update["competitors"] = []
            if not product:
                update["product"] = None
        if product:
            update["product"] = product
        return partial.model_copy(update=update)

    @staticmethod
    def _apply_listing_subject_to_intent(
        intent: IntentUnderstandingResult,
        content: str,
    ) -> IntentUnderstandingResult:
        subject = extract_listing_subject_company(content)
        if not subject:
            return intent
        product = intent.product
        if "外卖" in subject or "外卖" in (content or ""):
            product = "外卖"
        elif "酒店" in subject or "酒店" in (content or ""):
            product = "酒店"
        elif intent.company and intent.company != subject:
            # Drop stale product from prior clarification (e.g. 外卖 leftover)
            product = None
        update: dict[str, Any] = {
            "company": subject,
            "raw_message": content,
            "product": product,
        }
        if looks_like_competitor_listing_query(content):
            update["needs_clarification"] = False
            update["clarification_question"] = None
            update["missing_fields"] = [
                f for f in (intent.missing_fields or []) if f != "competitors"
            ]
            if intent.company and intent.company != subject:
                update["competitors"] = []
        return intent.model_copy(update=update)

    @staticmethod
    def _understanding_summary(
        intent: IntentUnderstandingResult,
        workflow_type: str | None,
        message_type: str | None = None,
    ) -> str | None:
        """Short UI hint: 已理解：飞猪 · 酒店 · 简答."""
        bits: list[str] = []
        if intent.company:
            bits.append(str(intent.company))
        if intent.product:
            bits.append(str(intent.product))
        wf = workflow_type or ""
        mt = message_type or ""
        if mt == "clarification" or wf == "clarification":
            bits.append("待补充")
        elif wf == "simple_question":
            bits.append("简答")
        elif wf == "information_query":
            bits.append("信息查询")
        elif wf in ("research", "intelligence_collection"):
            bits.append("信息收集")
        elif wf == "competitive_analysis":
            bits.append("竞品分析")
        elif wf == "follow_up":
            bits.append("追问")
        elif wf == "out_of_scope":
            bits.append("超出范围")
        if not bits:
            return None
        return " · ".join(bits)

    def _maybe_suggest_competitors(
        self,
        content: str,
        intent: IntentUnderstandingResult,
        memory: ProjectMemory | None = None,
    ) -> list[str]:
        text = content or ""
        if not looks_like_competitor_listing_query(text):
            return []
        pack = resolve_competitor_suggestions(
            intent.company,
            intent.product,
            memory,
            intent_competitors=list(intent.competitors or []),
        )
        return list(pack.get("peers") or [])

    def _recover_suggested_competitors(self, conversation_id: str) -> list[str]:
        messages = self._message_store.list_messages_by_conversation(conversation_id)
        for message in reversed(messages):
            meta = message.metadata or {}
            if meta.get("message_type") == "analysis_started":
                break
            raw = meta.get("suggested_competitors")
            if isinstance(raw, list) and raw:
                company = None
                intent_blob = meta.get("intent")
                if isinstance(intent_blob, dict):
                    company = intent_blob.get("company")
                return sanitize_competitors([str(x) for x in raw], company)
            intent_blob = meta.get("intent")
            if isinstance(intent_blob, dict) and intent_blob.get("competitors"):
                return sanitize_competitors(
                    [str(x) for x in intent_blob["competitors"]],
                    intent_blob.get("company"),
                )
        return []

    @staticmethod
    def _attach_memory_optional(report_request: Any, memory: ProjectMemory | None) -> Any:
        blob = memory_to_optional_dict(memory)
        if not blob:
            return report_request
        optional = dict(report_request.optional or {})
        optional["project_memory"] = blob
        return report_request.model_copy(update={"optional": optional})

    @staticmethod
    def _attach_knowledge_optional(
        report_request: Any,
        notes: list[KnowledgeNote] | None,
    ) -> Any:
        blob = KnowledgeService.optional_blob(notes)
        if not blob:
            return report_request
        optional = dict(report_request.optional or {})
        optional["knowledge_notes"] = blob
        return report_request.model_copy(update={"optional": optional})

    def _intent_for_follow_up_upgrade(
        self,
        intent: IntentUnderstandingResult,
        messages: list[Message],
        project_memory: ProjectMemory | None = None,
    ) -> IntentUnderstandingResult:
        """Build a launchable competitive_analysis intent from prior analysis + overlay."""
        base = select_best_prior_analysis_intent(messages)
        if not base and project_memory and project_memory.entities.our_company:
            ents = project_memory.entities
            base = {
                "type": "competitive_analysis",
                "company": ents.our_company,
                "competitors": list(ents.competitors),
                "product": ents.product,
                "objective": (
                    project_memory.last_objectives[0]
                    if project_memory.last_objectives
                    else "product_improvement"
                ),
                "confidence": 0.8,
                "raw_message": intent.raw_message,
            }
        if not base:
            raise ValueError(
                "follow_up upgrade requires a prior deep analysis with company/product"
            )
        merged = merge_intent_for_upgrade(base, intent)
        if not merged.company or not merged.product:
            raise ValueError(
                "follow_up upgrade requires company and product from prior context"
            )
        if not merged.competitors:
            raise ValueError(
                "follow_up upgrade requires competitors from prior context"
            )
        return merged

    @staticmethod
    def _validated_input_snapshot(
        report_request: Any,
        intent: IntentUnderstandingResult,
    ) -> dict[str, Any]:
        """Persist launch entities on analysis_started for later follow_up upgrade."""
        return {
            "our_company": report_request.our_company,
            "competitor_company": report_request.competitor_company,
            "competitors": list(intent.competitors or []),
            "product": report_request.product,
            "objective": report_request.objective,
            "scene": report_request.scene,
            "raw_message": intent.raw_message,
            "confidence": float(intent.confidence or 0.9),
        }

    def _recover_partial(self, conversation_id: str) -> IntentUnderstandingResult | None:
        messages = self._message_store.list_messages_by_conversation(conversation_id)
        recovered: IntentUnderstandingResult | None = None
        suggested: list[str] = []
        for message in reversed(messages):
            meta = message.metadata or {}
            mt = meta.get("message_type")
            if mt == "analysis_started":
                if recovered is None:
                    return None
                break
            if isinstance(meta.get("suggested_competitors"), list) and not suggested:
                suggested = [str(x) for x in meta["suggested_competitors"] if x]
            if recovered is not None or not meta.get("intent"):
                continue
            if mt not in (
                "clarification",
                "question_answered",
                "query_answered",
                None,
            ):
                continue
            try:
                candidate = IntentUnderstandingResult.model_validate(meta["intent"])
            except Exception:
                continue
            if (
                mt in ("clarification", "question_answered", "query_answered")
                or candidate.company
                or candidate.competitors
                or candidate.product
            ):
                recovered = candidate
        if recovered is None:
            return None
        comps = sanitize_competitors(list(recovered.competitors or []), recovered.company)
        if not comps and suggested:
            comps = sanitize_competitors(suggested, recovered.company)
        if comps != list(recovered.competitors or []):
            product = recovered.product or infer_default_product(recovered.company)
            missing = [
                f for f in (recovered.missing_fields or [])
                if f not in ("competitors", "product")
            ]
            if not recovered.company:
                missing.append("company")
            if not product:
                missing.append("product")
            if not comps:
                missing.append("competitors")
            recovered = recovered.model_copy(
                update={
                    "competitors": comps,
                    "product": product,
                    "missing_fields": missing,
                    "needs_clarification": bool(missing),
                    "clarification_question": (
                        recovered.clarification_question if missing else None
                    ),
                },
            )
        return recovered

    def _collection_started_message(
        self,
        intent: IntentUnderstandingResult,
        mode_label: str = "快速模式",
    ) -> str:
        parts = [
            f"已收到信息收集请求：{intent.company} · {intent.product}",
            f"收集模式：{mode_label}",
        ]
        if intent.raw_message:
            parts.append(f"主题：{intent.raw_message}")
        parts.append("正在检索公开信息并整理摘要，不会生成完整竞品分析报告。")
        return "\n".join(parts)

    def _analysis_started_message(
        self,
        intent: IntentUnderstandingResult,
        mode_label: str = "快速模式",
    ) -> str:
        competitors = "、".join(intent.competitors)
        parts = [
            f"已收到分析请求：{intent.company} 的 {intent.product}",
            f"对比竞品：{competitors}",
            f"分析模式：{mode_label}",
        ]
        if intent.objective:
            parts.append(f"分析目标：{intent.objective}")
        parts.append("正在启动分析，请稍候…")
        return "\n".join(parts)

    async def _publish_turn_progress(
        self,
        conversation_id: str,
        *,
        phase: str,
        stage_hint: str,
        progress: int = 0,
    ) -> None:
        if not self._event_bus:
            return
        await self._event_bus.publish(ConversationEvent(
            event="phase_update",
            conversation_id=conversation_id,
            task_id=None,
            timestamp=datetime.now(timezone.utc),
            data={
                "phase": phase,
                "progress": progress,
                "stage_hint": stage_hint,
            },
        ))

    async def _publish_analysis_started(
        self,
        conversation_id: str,
        task_id: str,
        report_id: str,
    ) -> None:
        if not self._event_bus:
            return
        await self._event_bus.publish(ConversationEvent(
            event="analysis_started",
            conversation_id=conversation_id,
            task_id=task_id,
            timestamp=datetime.now(timezone.utc),
            data={"task_id": task_id, "report_id": report_id},
        ))
