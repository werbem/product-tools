"""PR5: fine-grained research progress, stage_hint, launcher merge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.application.services.workflow_launcher import DeepAnalysisWorkflowLauncher
from app.infrastructure.agents.research_agent import ResearchAgent
from app.infrastructure.persistence import task_report_runtime
from app.infrastructure.workflow.progress_hints import RESEARCH_PROGRESS_HINTS
from app.infrastructure.workflow.progress_merge import merge_progress
from app.infrastructure.workflow.stream import push_event
from app.interfaces.api.routes.tasks import get_task_progress


class TestProgressMerge:
    def test_merge_never_regresses(self):
        assert merge_progress(36.0, 28.0) == 36.0
        assert merge_progress(70.0, 85.0) == 85.0


class TestTouchTaskProgress:
    def test_touch_merges_progress_and_sets_stage_hint(self):
        task_id = "pr5-touch"
        task_report_runtime.get_tasks()[task_id] = {
            "task_id": task_id,
            "status": "running",
            "state": {"progress": 28.0},
        }
        with patch("app.infrastructure.workflow.stream.push_event") as push:
            task_report_runtime.touch_task_progress(
                task_id,
                current_phase="researching",
                progress=24.0,
                current_agent="research",
                stage_hint=RESEARCH_PROGRESS_HINTS[24.0],
            )
        state = task_report_runtime.get_tasks()[task_id]["state"]
        assert state["progress"] == 28.0
        assert state["stage_hint"] == RESEARCH_PROGRESS_HINTS[24.0]
        push.assert_called_once()
        extra = push.call_args.kwargs.get("extra") or {}
        assert extra.get("stage_hint") == RESEARCH_PROGRESS_HINTS[24.0]


class TestResearchProgressPoints:
    def test_touch_research_progress_uses_hints(self):
        with patch(
            "app.infrastructure.persistence.task_report_runtime.touch_task_progress",
        ) as touch:
            ResearchAgent._touch_research_progress("t1", 32.0, RESEARCH_PROGRESS_HINTS[32.0])
        touch.assert_called_once_with(
            "t1",
            current_phase="researching",
            progress=32.0,
            current_agent="research",
            stage_hint=RESEARCH_PROGRESS_HINTS[32.0],
        )

    @pytest.mark.asyncio
    async def test_extract_start_touches_32_and_evaluator_36(self):
        agent = ResearchAgent()
        input_data = MagicMock()
        input_data.max_evidence_items = None
        input_data.max_evaluated_items = None
        input_data.skip_evidence_evaluation = True

        touches: list[float] = []

        def record_touch(task_id, progress, stage_hint):
            touches.append(progress)

        with patch.object(agent, "_touch_research_progress", side_effect=record_touch):
            items, _summary = await agent._extract_evidence_from_sources(
                "objective",
                [],
                input_data,
                4,
                lambda: 999.0,
                task_id="t-extract",
            )

        assert 32.0 in touches
        assert 36.0 in touches
        assert items == []


class TestTaskProgressApi:
    @pytest.mark.asyncio
    async def test_progress_api_returns_stage_hint(self):
        from uuid import uuid4

        task_id = str(uuid4())
        task_report_runtime.get_tasks()[task_id] = {
            "task_id": task_id,
            "status": "running",
            "state": {
                "current_phase": "researching",
                "current_agent": "research",
                "progress": 32.0,
                "stage_hint": RESEARCH_PROGRESS_HINTS[32.0],
                "total_elapsed_s": 42.5,
                "phase_history": [],
            },
        }
        resp = await get_task_progress(task_id)
        assert resp.stage_hint == RESEARCH_PROGRESS_HINTS[32.0]
        assert resp.total_elapsed_s == 42.5
        assert resp.progress == 32.0


class TestLauncherProgressMerge:
    def test_launcher_merge_preserves_higher_mid_node_progress(self):
        merged = merge_progress(36.0, float(40))
        assert merged == 40.0
        merged2 = merge_progress(80.0, float(72))
        assert merged2 == 80.0


class TestStreamStageHint:
    def test_push_event_includes_stage_hint(self):
        task_id = "pr5-sse"
        from app.infrastructure.workflow.stream import _get_queue

        _get_queue(task_id)
        push_event(
            task_id,
            agent="research",
            status="running",
            message="正在分析网页内容…",
            progress=32.0,
            extra={"stage_hint": "正在分析网页内容…", "phase": "research"},
        )
        queue = _get_queue(task_id)
        event = queue.get_nowait()
        assert event["stage_hint"] == "正在分析网页内容…"
        assert event["data"]["stage_hint"] == "正在分析网页内容…"
