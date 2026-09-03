"""Conversation SSE event payload shape."""

from __future__ import annotations

import pytest

from app.application.dto.conversation_event_dto import ConversationEvent
from datetime import datetime, timezone


def test_phase_update_accepts_stage_hint():
    event = ConversationEvent(
        event="phase_update",
        conversation_id="c1",
        task_id="t1",
        timestamp=datetime.now(timezone.utc),
        data={
            "phase": "research",
            "progress": 32,
            "stage_hint": "正在分析网页内容…",
            "total_elapsed_s": 10.5,
        },
    )
    assert event.data["stage_hint"] == "正在分析网页内容…"
    assert event.data["progress"] == 32
