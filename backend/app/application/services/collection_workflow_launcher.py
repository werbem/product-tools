"""Intelligence collection workflow launcher — routes to collect_graph only."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from app.application.dto.conversation_event_dto import ConversationEvent
from app.application.dto.report_dto import ReportCreateRequest
from app.application.dto.workflow_launch_dto import WorkflowLaunchContext, WorkflowLaunchResult
from app.application.services.artifact_service import ArtifactService
from app.application.services.collection_formatter import (
    build_collection_document_meta,
    build_collection_markdown,
)
from app.infrastructure.events.conversation_event_bus import ConversationEventBus
from app.infrastructure.persistence import task_report_runtime
from app.infrastructure.trace import TraceStatus, trace_collector
from app.infrastructure.workflow.analysis_mode import get_mode_config
from app.infrastructure.workflow.state import create_initial_state
from app.infrastructure.workflow.stream import ensure_listener

logger = logging.getLogger(__name__)

_COLLECT_NODE_PHASE = {
    "collect_validate_node": "validated",
    "collect_plan_node": "planned",
    "research_node": "researched",
    "prepare_collection_output": "collection_processed",
    "collection_output_node": "collection_completed",
}

_COLLECT_PHASE_PROGRESS = {
    "validated": 10.0,
    "planned": 25.0,
    "researched": 80.0,
    "collection_processed": 95.0,
    "collection_completed": 100.0,
}


class CollectionWorkflowLauncher:
    def __init__(
        self,
        event_bus: ConversationEventBus | None = None,
        artifact_service: ArtifactService | None = None,
        memory_writer: Any | None = None,
    ) -> None:
        self._event_bus = event_bus
        self._artifact_service = artifact_service
        self._memory_writer = memory_writer
        self._running: set[asyncio.Task[Any]] = set()

    async def launch(
        self,
        request: ReportCreateRequest,
        context: WorkflowLaunchContext | None = None,
    ) -> WorkflowLaunchResult:
        from app.infrastructure.workflow.collect_graph import collect_graph

        payload = request.model_dump()
        optional = dict(payload.get("optional") or {})
        optional.setdefault("workflow_kind", "intelligence_collection")
        optional.setdefault("skip_evidence_evaluation", True)
        payload["optional"] = optional

        state = create_initial_state(payload)
        task_id_str = str(state["task_id"])
        ctx = context or WorkflowLaunchContext()

        trace_collector.record_trace(
            task_id=task_id_str,
            stage="api",
            agent_name="",
            status=TraceStatus.SUCCESS,
            input_summary=f"collect our={request.our_company}, product={request.product}",
            output_summary=f"task_id={task_id_str}",
            metadata={"method": "collection_launcher", "params": payload},
        )

        entry: dict[str, Any] = {
            "task_id": task_id_str,
            "status": "pending",
            "workflow_kind": "intelligence_collection",
            "state": state,
        }
        if ctx.project_id:
            entry["project_id"] = ctx.project_id
        if ctx.conversation_id:
            entry["conversation_id"] = ctx.conversation_id
        if ctx.source_message_id:
            entry["source_message_id"] = ctx.source_message_id

        tasks = task_report_runtime.get_tasks()
        tasks[task_id_str] = entry
        task_report_runtime.persist_tasks()
        ensure_listener(task_id_str)

        bg = asyncio.create_task(
            self._run_collection(task_id_str, request, collect_graph),
        )
        self._running.add(bg)
        bg.add_done_callback(lambda t: self._running.discard(t))

        return WorkflowLaunchResult(task_id=task_id_str, report_id=task_id_str, status="pending")

    async def _run_collection(
        self,
        task_id_str: str,
        body: ReportCreateRequest,
        collect_graph: Any,
    ) -> None:
        tasks = task_report_runtime.get_tasks()
        entry = tasks.get(task_id_str, {})
        state = entry.get("state", {})
        conversation_id = entry.get("conversation_id")

        mode = "fast"
        optional = (body.optional or {}) if hasattr(body, "optional") else {}
        if isinstance(optional, dict):
            mode = str(optional.get("analysis_mode") or "fast")
        cfg = get_mode_config(mode)
        timeout_s = cfg.research_timeout_s + 30.0

        try:
            final_state = dict(state)
            phase_history: list[dict[str, Any]] = []

            async def _consume_graph() -> None:
                nonlocal final_state, phase_history
                async for chunk in collect_graph.astream(state, stream_mode="updates"):
                    for node_name, node_state in chunk.items():
                        final_state.update(node_state)
                        phase_name = _COLLECT_NODE_PHASE.get(node_name)
                        if phase_name:
                            now = datetime.utcnow().isoformat()
                            phase_history.append({
                                "phase": phase_name,
                                "entered_at": now,
                                "duration_ms": 0,
                                "status": "completed",
                            })
                            final_state["phase_history"] = list(phase_history)
                            final_state["progress"] = float(
                                _COLLECT_PHASE_PROGRESS.get(
                                    phase_name, final_state.get("progress", 0.0),
                                ),
                            )
                            final_state["current_agent"] = phase_name
                            entry["state"] = dict(final_state)
                            task_report_runtime.touch_task_progress(
                                task_id_str,
                                current_phase=phase_name,
                                progress=float(final_state["progress"]),
                                current_agent=phase_name,
                            )
                            await self._publish_phase_update(
                                conversation_id, task_id_str, phase_name, final_state,
                            )

            await asyncio.wait_for(_consume_graph(), timeout=timeout_s)

            final_phase = final_state.get("current_phase", "")
            if final_phase in {"collection_failed", "validation_failed", "failed"}:
                entry["status"] = "failed"
                entry["error"] = (
                    "; ".join(str(e) for e in final_state.get("errors", []) if e)
                    or "信息收集失败"
                )
                await self._publish_analysis_failed(conversation_id, task_id_str, entry["error"])
            else:
                markdown = build_collection_markdown(final_state)
                topic_meta = build_collection_document_meta(final_state)
                final_state["collection_document"] = {
                    "markdown": markdown,
                    "evidence_count": len(
                        (final_state.get("evidence_bundle") or {}).get("evidence_items") or [],
                    ),
                    "generated_at": datetime.utcnow().isoformat(),
                    **topic_meta,
                }
                final_state["progress"] = 100.0
                final_state["current_phase"] = "collection_completed"
                entry["status"] = "completed"
                entry["state"] = dict(final_state)
                artifact_status, artifact_id = await self._finalize_artifact(entry, task_id_str, body)
                self._write_project_memory(entry, task_id_str, body, final_state)
                await self._publish_completion(
                    conversation_id, task_id_str, artifact_status, artifact_id,
                )
        except asyncio.TimeoutError:
            error_msg = f"信息收集超时（{int(timeout_s)}s）"
            entry["status"] = "failed"
            entry["error"] = error_msg
            if entry.get("state"):
                entry["state"]["error_info"] = error_msg
            await self._publish_analysis_failed(conversation_id, task_id_str, error_msg)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            entry["status"] = "failed"
            entry["error"] = error_msg
            if entry.get("state"):
                entry["state"]["error_info"] = error_msg
            await self._publish_analysis_failed(conversation_id, task_id_str, error_msg)
            logger.exception("collection workflow failed for task %s", task_id_str)
        finally:
            tasks[task_id_str] = entry
            task_report_runtime.persist_tasks()

    def _write_project_memory(
        self,
        entry: dict[str, Any],
        task_id_str: str,
        body: ReportCreateRequest,
        final_state: dict[str, Any],
    ) -> None:
        if not self._memory_writer:
            return
        project_id = entry.get("project_id")
        if not project_id:
            return
        doc = final_state.get("collection_document") or {}
        topic = None
        if isinstance(doc, dict):
            topic = doc.get("topic")
        evidence_items = (final_state.get("evidence_bundle") or {}).get("evidence_items") or []
        titles: list[str] = []
        for item in evidence_items:
            if isinstance(item, dict) and item.get("title"):
                titles.append(str(item["title"]))
        try:
            self._memory_writer.upsert_from_collection_success(
                project_id=str(project_id),
                conversation_id=entry.get("conversation_id"),
                task_id=task_id_str,
                our_company=body.our_company,
                product=body.product,
                topic=str(topic) if topic else None,
                objective=body.scene or body.objective,
                evidence_titles=titles,
                competitor_company=body.competitor_company,
            )
        except Exception:
            logger.exception("collection memory upsert failed task=%s", task_id_str)

    async def _finalize_artifact(
        self,
        entry: dict[str, Any],
        task_id_str: str,
        body: ReportCreateRequest,
    ) -> tuple[str, str | None]:
        if entry.get("artifact_status"):
            return entry.get("artifact_status", "skipped"), entry.get("artifact_id")
        project_id = entry.get("project_id")
        if not project_id or not self._artifact_service:
            entry["artifact_status"] = "skipped"
            return "skipped", None
        if entry.get("status") == "failed":
            return "skipped", None
        try:
            title = f"{body.our_company} · {body.product} 信息收集"
            artifact = self._artifact_service.create_evidence_artifact(
                project_id=project_id,
                conversation_id=entry.get("conversation_id"),
                task_id=task_id_str,
                title=title,
            )
            entry["artifact_status"] = "created"
            entry["artifact_id"] = artifact.id
            return "created", artifact.id
        except Exception as exc:
            entry["artifact_status"] = "failed"
            entry["artifact_error"] = f"{type(exc).__name__}: {exc}"
            return "failed", None

    async def _publish_phase_update(
        self,
        conversation_id: str | None,
        task_id: str,
        phase: str,
        state: dict[str, Any],
    ) -> None:
        if not self._event_bus or not conversation_id:
            return
        await self._event_bus.publish(ConversationEvent(
            event="phase_update",
            conversation_id=conversation_id,
            task_id=task_id,
            timestamp=datetime.now(timezone.utc),
            data={"phase": phase, "progress": state.get("progress", 0)},
        ))

    async def _publish_analysis_failed(
        self,
        conversation_id: str | None,
        task_id: str,
        error: str,
    ) -> None:
        if not self._event_bus or not conversation_id:
            return
        await self._event_bus.publish(ConversationEvent(
            event="analysis_failed",
            conversation_id=conversation_id,
            task_id=task_id,
            timestamp=datetime.now(timezone.utc),
            data={"error": error},
        ))

    async def _publish_completion(
        self,
        conversation_id: str | None,
        task_id: str,
        artifact_status: str,
        artifact_id: str | None,
    ) -> None:
        if not self._event_bus or not conversation_id:
            return
        if artifact_status == "created" and artifact_id:
            await self._event_bus.publish(ConversationEvent(
                event="artifact_created",
                conversation_id=conversation_id,
                task_id=task_id,
                timestamp=datetime.now(timezone.utc),
                data={"artifact_id": artifact_id, "artifact_type": "evidence_package"},
            ))
        await self._event_bus.publish(ConversationEvent(
            event="analysis_completed",
            conversation_id=conversation_id,
            task_id=task_id,
            timestamp=datetime.now(timezone.utc),
            data={
                "artifact_status": artifact_status,
                "artifact_id": artifact_id,
                "workflow_kind": "intelligence_collection",
            },
        ))
