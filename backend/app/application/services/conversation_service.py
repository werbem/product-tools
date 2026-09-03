"""Conversation application service."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.application.dto.conversation_dto import ConversationTurnResult, TurnStatus
from app.application.dto.conversation_event_dto import ConversationEvent
from app.application.dto.intent_dto import IntentUnderstandingRequest, IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext, RoutingDecision
from app.application.dto.workflow_launch_dto import WorkflowLaunchContext
from app.application.exceptions import ConversationNotFoundError, ProjectArchivedError, ProjectNotFoundError
from app.application.services.intent_mapper import to_report_create_request
from app.application.services.intent_understanding_service import IntentUnderstandingService
from app.application.services.knowledge_service import KnowledgeService
from app.application.services.project_service import ProjectService
from app.application.services.collection_workflow_launcher import CollectionWorkflowLauncher
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

            user_message = Message(
                id=new_id(),
                conversation_id=conversation_id,
                role="user",
                content=content,
            )
            self._message_store.append_message(user_message)

            partial = self._recover_partial(conversation_id)
            memory = self._load_project_memory(conversation.project_id)
            knowledge_notes = self._retrieve_knowledge_notes(
                conversation.project_id, content,
            )
            knowledge_block = format_knowledge_prompt_block(knowledge_notes) or None
            partial = self._merge_memory_partial(partial, memory, raw_message=content)
            intent = await self._intent_service.understand(IntentUnderstandingRequest(
                message=content,
                partial=partial,
                conversation_id=conversation_id,
            ))
            # Fill any remaining empty entity slots from Memory after LLM
            intent = self._fill_intent_from_memory(intent, memory)

            status: TurnStatus
            task_id: str | None = None
            report_id: str | None = None
            assistant_content: str
            message_type: str
            routing_decision: RoutingDecision | None = None
            assistant_metadata: dict[str, Any] = {"intent": intent.model_dump()}

            if intent.needs_clarification:
                # Light query / follow_up must not be blocked by competitor clarification
                probe = self._router.route(
                    intent,
                    content,
                    self._build_routing_context(conversation, conversation_id),
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
                                "请补充：我方公司、对比竞品、以及产品或场景。\n"
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
                            scene_extra = (
                                f"{report_request.scene or ''}\n"
                                f"【追问升级】{content}\n"
                                f"【上轮上下文摘要】\n{follow.context_summary}"
                            ).strip()
                            optional = dict(report_request.optional or {})
                            optional.update({
                                "follow_up": True,
                                "prior_task_id": follow.prior_task_id,
                                "prior_report_id": follow.prior_report_id,
                                "follow_up_context": follow.context_summary[:2000],
                                "raw_message": content,
                            })
                            report_request = report_request.model_copy(
                                update={"scene": scene_extra[:2500], "optional": optional},
                            )
                            report_request = self._attach_memory_optional(report_request, memory)
                            report_request = self._attach_knowledge_optional(
                                report_request, knowledge_notes,
                            )
                            launch_result = await launcher.launch(
                                report_request,
                                WorkflowLaunchContext(
                                    project_id=conversation.project_id,
                                    conversation_id=conversation_id,
                                    source_message_id=user_message.id,
                                ),
                            )
                            status = "analysis_started"
                            message_type = "analysis_started"
                            task_id = launch_result.task_id
                            report_id = launch_result.report_id
                            mode_label = "完整模式" if analysis_mode == "full" else "快速模式"
                            assistant_content = (
                                "已基于上一轮结果启动完整竞品分析（追问升级）。\n"
                                f"分析模式：{mode_label}\n正在启动分析，请稍候…"
                            )
                            assistant_metadata.update({
                                "task_id": task_id,
                                "report_id": report_id,
                                "workflow_type": "deep_analysis",
                                "workflow_kind": "deep_analysis",
                                "analysis_mode": analysis_mode,
                                "follow_up_mode": "upgrade_analysis",
                                "prior_task_id": follow.prior_task_id,
                                "prior_report_id": follow.prior_report_id,
                                "routing_debug": optional.get("routing_debug"),
                                "validated_input": self._validated_input_snapshot(
                                    report_request, launch_intent,
                                ),
                            })
                            await self._publish_analysis_started(conversation_id, task_id, report_id)
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
                    report_request = to_report_create_request(
                        intent, analysis_mode=analysis_mode,
                    )
                    report_request = self._attach_memory_optional(report_request, memory)
                    report_request = self._attach_knowledge_optional(
                        report_request, knowledge_notes,
                    )
                    launch_result = await launcher.launch(
                        report_request,
                        WorkflowLaunchContext(
                            project_id=conversation.project_id,
                            conversation_id=conversation_id,
                            source_message_id=user_message.id,
                        ),
                    )
                    status = "analysis_started"
                    message_type = "analysis_started"
                    task_id = launch_result.task_id
                    report_id = launch_result.report_id
                    mode_label = "完整模式" if analysis_mode == "full" else "快速模式"
                    assistant_content = self._collection_started_message(intent, mode_label)
                    # Dual-write: UI still keys off intelligence_collection
                    assistant_metadata.update({
                        "task_id": task_id,
                        "report_id": report_id,
                        "workflow_type": "intelligence_collection",
                        "workflow_kind": "intelligence_collection",
                        "analysis_mode": analysis_mode,
                        "routing_debug": (report_request.optional or {}).get("routing_debug"),
                    })
                    await self._publish_analysis_started(conversation_id, task_id, report_id)
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
                    report_request = to_report_create_request(
                        intent, analysis_mode=analysis_mode,
                    )
                    report_request = self._attach_memory_optional(report_request, memory)
                    report_request = self._attach_knowledge_optional(
                        report_request, knowledge_notes,
                    )
                    launch_result = await launcher.launch(
                        report_request,
                        WorkflowLaunchContext(
                            project_id=conversation.project_id,
                            conversation_id=conversation_id,
                            source_message_id=user_message.id,
                        ),
                    )
                    status = "analysis_started"
                    message_type = "analysis_started"
                    task_id = launch_result.task_id
                    report_id = launch_result.report_id
                    mode_label = "完整模式" if analysis_mode == "full" else "快速模式"
                    assistant_content = self._analysis_started_message(intent, mode_label)
                    assistant_metadata.update({
                        "task_id": task_id,
                        "report_id": report_id,
                        "workflow_type": "deep_analysis",
                        "workflow_kind": "deep_analysis",
                        "analysis_mode": analysis_mode,
                        "routing_debug": (report_request.optional or {}).get("routing_debug"),
                        "validated_input": self._validated_input_snapshot(report_request, intent),
                    })
                    await self._publish_analysis_started(conversation_id, task_id, report_id)
            else:
                status = "out_of_scope"
                message_type = "out_of_scope"
                assistant_content = _OUT_OF_SCOPE_REPLY

            assistant_metadata["message_type"] = message_type
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

    def _retrieve_knowledge_notes(
        self,
        project_id: str,
        query: str,
    ) -> list[KnowledgeNote]:
        try:
            return self._knowledge.retrieve_for_prompt(project_id, query)
        except Exception:
            return []

    @staticmethod
    def _merge_memory_partial(
        partial: IntentUnderstandingResult | None,
        memory: ProjectMemory | None,
        *,
        raw_message: str,
    ) -> IntentUnderstandingResult | None:
        """Clarification partial wins non-empty; Memory fills empty slots only."""
        if not memory:
            return partial
        ents = memory.entities
        if not (ents.our_company or ents.product or ents.competitors):
            return partial
        if partial is None:
            return IntentUnderstandingResult(
                type="competitive_analysis",
                company=ents.our_company,
                competitors=list(ents.competitors),
                product=ents.product,
                objective=memory.last_objectives[0] if memory.last_objectives else None,
                confidence=0.7,
                needs_clarification=False,
                raw_message=raw_message,
            )
        return IntentUnderstandingResult(
            type=partial.type,
            company=partial.company or ents.our_company,
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
        company = intent.company or ents.our_company
        product = intent.product or ents.product
        competitors = list(intent.competitors or []) or list(ents.competitors or [])
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
        if not product:
            missing.append("product")
        needs = bool(missing) and intent.type == "competitive_analysis"
        return intent.model_copy(
            update={
                "company": company,
                "product": product,
                "competitors": competitors,
                "missing_fields": missing if needs else [],
                "needs_clarification": needs,
                "clarification_question": (
                    intent.clarification_question if needs else None
                ),
            },
        )

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
        for message in reversed(messages):
            meta = message.metadata or {}
            if meta.get("message_type") == "analysis_started":
                return None
            if meta.get("message_type") == "clarification" and meta.get("intent"):
                try:
                    return IntentUnderstandingResult.model_validate(meta["intent"])
                except Exception:
                    continue
        return None

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
