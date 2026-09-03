"""Deep Analysis Workflow Launcher."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.application.dto.conversation_event_dto import ConversationEvent
from app.application.dto.report_dto import (
    ReportCreateRequest,
    ReportDetailResponse,
    ReportGenerationMetadataDTO,
    ReportSectionDTO,
)
from app.application.dto.workflow_launch_dto import WorkflowLaunchContext, WorkflowLaunchResult
from app.application.services.artifact_service import ArtifactService
from app.domain.entities.artifact import Artifact, stable_report_artifact_id
from app.infrastructure.events.conversation_event_bus import ConversationEventBus
from app.infrastructure.persistence import task_report_runtime
from app.infrastructure.trace import TraceStatus, trace_collector
from app.infrastructure.workflow.state import create_initial_state
from app.infrastructure.workflow.stream import ensure_listener

from app.infrastructure.workflow.progress_merge import merge_progress
from app.infrastructure.workflow.progress_hints import PHASE_COMPLETION_HINTS

logger = logging.getLogger(__name__)

_PHASE_NODE_MAP = {
    "validate_input_node": "validated",
    "plan_node": "planned",
    "research_node": "researched",
    "compare_node": "compared",
    "insight_node": "insighted",
    "strategy_node": "strategized",
    "report_node": "reported",
    "review_node": "reviewed",
}

_PHASE_PROGRESS = {
    "validated": 5, "planned": 15, "researched": 40,
    "compared": 55, "insighted": 65, "strategized": 72,
    "reported": 85, "reviewed": 95,
}


def _build_report_metadata(
    final_state: dict[str, Any],
    report_doc: dict[str, Any],
) -> ReportGenerationMetadataDTO | None:
    from app.infrastructure.workflow.analysis_mode import resolve_analysis_mode

    doc_meta = report_doc.get("metadata") if isinstance(report_doc, dict) else {}
    if not isinstance(doc_meta, dict):
        doc_meta = {}

    analysis_mode = resolve_analysis_mode(final_state)
    generation_mode = doc_meta.get("generation_mode")
    generation_note = doc_meta.get("generation_note")
    raw_timeouts = doc_meta.get("segment_timeouts")
    segment_timeouts = list(raw_timeouts) if isinstance(raw_timeouts, list) else []

    return ReportGenerationMetadataDTO(
        generation_mode=generation_mode,
        generation_note=generation_note,
        segment_timeouts=segment_timeouts,
        analysis_mode=analysis_mode,
    )


class DeepAnalysisWorkflowLauncher:
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

    def has_in_process_tasks(self) -> bool:
        """True while a background Deep asyncio.Task is still running (this worker)."""
        return bool(self._running)

    async def launch(
        self,
        request: ReportCreateRequest,
        context: WorkflowLaunchContext | None = None,
    ) -> WorkflowLaunchResult:
        from app.infrastructure.workflow.graph import workflow_graph

        state = create_initial_state(request.model_dump())
        task_id_str = str(state["task_id"])
        ctx = context or WorkflowLaunchContext()

        trace_collector.record_trace(
            task_id=task_id_str,
            stage="api",
            agent_name="",
            status=TraceStatus.SUCCESS,
            input_summary=f"launch our={request.our_company}, competitor={request.competitor_company}",
            output_summary=f"task_id={task_id_str}",
            metadata={"method": "launcher", "params": request.model_dump()},
        )

        entry: dict[str, Any] = {
            "task_id": task_id_str,
            "status": "pending",
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

        bg = asyncio.create_task(self._run_workflow(task_id_str, request, workflow_graph))
        self._running.add(bg)
        bg.add_done_callback(lambda t: self._running.discard(t))

        return WorkflowLaunchResult(task_id=task_id_str, report_id=task_id_str, status="pending")

    async def wait_for_background_tasks(self) -> None:
        if self._running:
            await asyncio.gather(*list(self._running), return_exceptions=True)

    async def _run_workflow(self, task_id_str: str, body: ReportCreateRequest, workflow_graph: Any) -> None:
        tasks = task_report_runtime.get_tasks()
        reports = task_report_runtime.get_reports()
        entry = tasks.get(task_id_str, {})
        state = entry.get("state", {})
        conversation_id = entry.get("conversation_id")

        try:
            final_state = dict(state)
            phase_history: list[dict[str, Any]] = []

            async for chunk in workflow_graph.astream(state, stream_mode="updates"):
                for node_name, node_state in chunk.items():
                    final_state.update(node_state)
                    phase_name = _PHASE_NODE_MAP.get(node_name)
                    if phase_name:
                        now = datetime.utcnow().isoformat()
                        phase_history.append({
                            "phase": phase_name,
                            "entered_at": now,
                            "duration_ms": 0,
                            "status": "completed",
                        })
                        final_state["phase_history"] = list(phase_history)
                        phase_progress = float(_PHASE_PROGRESS.get(phase_name, 0))
                        final_state["progress"] = merge_progress(
                            final_state.get("progress"),
                            phase_progress,
                        )
                        if not final_state.get("stage_hint"):
                            final_state["stage_hint"] = PHASE_COMPLETION_HINTS.get(
                                phase_name,
                                "",
                            ) or None
                        final_state["current_agent"] = phase_name
                        entry["state"] = dict(final_state)
                        await self._publish_phase_update(conversation_id, task_id_str, phase_name, final_state)

            final_phase = final_state.get("current_phase", "")
            if "fail" in str(final_phase) or final_phase == "validation_failed":
                entry["status"] = "failed"
                entry["error"] = (
                    "; ".join(str(e) for e in final_state.get("errors", []) if e) or "分析流程失败"
                )
                await self._publish_analysis_failed(conversation_id, task_id_str, entry["error"])
            else:
                entry["status"] = "completed"
                report_doc = final_state.get("report_document") or {}
                sections_data = report_doc.get("sections", []) if isinstance(report_doc, dict) else []
                evidence_list = (
                    (final_state.get("evidence_bundle") or {}).get("sources_used")
                    or (final_state.get("evidence_bundle") or {}).get("sources")
                    or []
                )
                report_metadata = _build_report_metadata(final_state, report_doc if isinstance(report_doc, dict) else {})
                reports[task_id_str] = ReportDetailResponse(
                    id=UUID(final_state["task_id"]),
                    task_id=UUID(final_state["task_id"]),
                    our_company=body.our_company,
                    competitor_company=body.competitor_company,
                    product=body.product,
                    objective=body.scene or body.objective,
                    markdown=(report_doc or {}).get("formats", {}).get("markdown"),
                    html=(report_doc or {}).get("formats", {}).get("html"),
                    word_url=f"/api/reports/{task_id_str}/download"
                    if (report_doc or {}).get("formats", {}).get("docx_url")
                    else None,
                    sections=[ReportSectionDTO(**s) for s in sections_data],
                    total_word_count=(report_doc or {}).get("metadata", {}).get("total_word_count", 0),
                    metadata=report_metadata,
                    created_at=datetime.utcnow(),
                    evidence_sources=evidence_list if evidence_list else None,
                ).model_dump()
                artifact_status, artifact_id = await self._finalize_artifact(entry, task_id_str, body)
                self._write_project_memory(entry, task_id_str, body, reports.get(task_id_str) or {})
                await self._publish_completion(
                    conversation_id, task_id_str, artifact_status, artifact_id,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            entry["status"] = "failed"
            entry["error"] = error_msg
            if entry.get("state"):
                entry["state"]["error_info"] = error_msg
            reports[task_id_str] = {
                "id": task_id_str,
                "task_id": task_id_str,
                "our_company": body.our_company,
                "competitor_company": body.competitor_company,
                "product": body.product,
                "objective": body.scene or body.objective,
                "status": "failed",
                "error": error_msg,
                "markdown": None,
                "html": None,
                "word_url": None,
                "sections": [],
                "total_word_count": 0,
                "created_at": datetime.utcnow().isoformat(),
            }
            await self._publish_analysis_failed(conversation_id, task_id_str, error_msg)
            logger.exception("workflow failed for task %s", task_id_str)
        finally:
            tasks[task_id_str] = entry
            task_report_runtime.persist_tasks()
            task_report_runtime.persist_reports()

    def _write_project_memory(
        self,
        entry: dict[str, Any],
        task_id_str: str,
        body: ReportCreateRequest,
        report: dict[str, Any],
    ) -> None:
        """Best-effort Memory upsert after Deep success — never raises to caller."""
        if not self._memory_writer:
            return
        project_id = entry.get("project_id")
        if not project_id:
            return
        optional = body.optional or {}
        competitors = optional.get("competitors") if isinstance(optional, dict) else None
        sections = report.get("sections") if isinstance(report, dict) else None
        markdown = report.get("markdown") if isinstance(report, dict) else None
        try:
            self._memory_writer.upsert_from_deep_success(
                project_id=str(project_id),
                conversation_id=entry.get("conversation_id"),
                task_id=task_id_str,
                our_company=body.our_company,
                competitor_company=body.competitor_company,
                product=body.product,
                objective=body.objective,
                scene=body.scene,
                competitors=list(competitors) if isinstance(competitors, list) else None,
                markdown=markdown,
                sections=list(sections) if isinstance(sections, list) else None,
                validated_input={
                    "our_company": body.our_company,
                    "competitor_company": body.competitor_company,
                    "competitors": list(competitors) if isinstance(competitors, list) else [],
                    "product": body.product,
                    "objective": body.objective,
                    "scene": body.scene,
                },
            )
        except Exception:
            logger.exception("deep memory upsert failed task=%s", task_id_str)

    async def _finalize_artifact(
        self,
        entry: dict[str, Any],
        task_id_str: str,
        body: ReportCreateRequest,
    ) -> tuple[str, str | None]:
        if entry.get("artifact_status"):
            return entry.get("artifact_status", "skipped"), entry.get("artifact_id")
        project_id = entry.get("project_id")
        if not project_id:
            entry["artifact_status"] = "skipped"
            return "skipped", None
        if not self._artifact_service:
            entry["artifact_status"] = "skipped"
            return "skipped", None
        if entry.get("status") == "failed":
            return "skipped", None
        try:
            artifact = self._artifact_service.create_report_artifact(
                project_id=project_id,
                conversation_id=entry.get("conversation_id"),
                task_id=task_id_str,
                report_id=task_id_str,
                title=f"{body.our_company} vs {body.competitor_company} 竞品分析报告",
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
            data={
                "phase": phase,
                "progress": state.get("progress", 0),
                "stage_hint": state.get("stage_hint"),
                "total_elapsed_s": (
                    state.get("total_elapsed_s")
                    or (state.get("workflow_budget_meta") or {}).get("total_elapsed_s")
                ),
            },
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
                data={"artifact_id": artifact_id},
            ))
        await self._event_bus.publish(ConversationEvent(
            event="analysis_completed",
            conversation_id=conversation_id,
            task_id=task_id,
            timestamp=datetime.now(timezone.utc),
            data={"artifact_status": artifact_status, "artifact_id": artifact_id},
        ))
