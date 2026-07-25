"""WorkflowState definition — the single shared state for the LangGraph.

Maps directly from the Workflow Design document section 1.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID, uuid4

from langgraph.graph import StateGraph as LGStateGraph
from typing_extensions import TypedDict


class PhaseRecord(TypedDict, total=False):
    phase: str
    entered_at: str
    duration_ms: int
    status: str           # running | completed | failed | skipped
    error: Optional[dict]


class ErrorRecord(TypedDict, total=False):
    code: str
    message: str
    node: str
    timestamp: str
    retryable: bool
    retry_count: int
    resolved: bool


class HumanCheckpoint(TypedDict, total=False):
    checkpoint_id: str
    node: str
    requested_at: str
    context: dict
    decision: Optional[dict]
    resolved_at: Optional[str]


class HumanDecisionRequest(TypedDict, total=False):
    checkpoint_id: str
    question: str
    context: dict
    timeout_minutes: int
    options: list[dict]


class StreamEvent(TypedDict, total=False):
    type: str
    phase: str
    data: Any
    timestamp: str
    sequence: int


class FinalReport(TypedDict, total=False):
    markdown: Optional[str]
    word_url: Optional[str]
    html: Optional[str]


class TokenUsage(TypedDict, total=False):
    total_prompt_tokens: int
    total_completion_tokens: int


class WorkflowState(TypedDict, total=False):
    # Demo mode flag — set by build_demo_full_state
    demo: bool
    """Shared state for the competitive analysis LangGraph.

    All keys are optional because state is accumulated incrementally.
    """

    # ── Task metadata ──
    task_id: str
    created_at: str
    updated_at: str

    # ── User input ──
    user_input: dict[str, Any]
    validated_input: dict[str, Any]

    # ── Execution context ──
    current_phase: str
    phase_history: list[PhaseRecord]
    progress: float

    # ── Evidence Intelligence ──
    clusters: Optional[list[dict[str, Any]]]

    # ── Agent outputs (accumulated) ──
    research_plan: Optional[dict[str, Any]]
    evidence_bundle: Optional[dict[str, Any]]
    gap_analysis: Optional[dict[str, Any]]
    insights: Optional[dict[str, Any]]
    strategic_insights: Optional[dict[str, Any]]
    report_document: Optional[dict[str, Any]]
    review_result: Optional[dict[str, Any]]

    # ── Error & retry ──
    errors: list[ErrorRecord]
    retry_counts: dict[str, int]

    # ── Streaming ──
    stream_events: list[StreamEvent]

    # ── Human-in-the-loop ──
    human_checkpoints: list[HumanCheckpoint]
    pending_human_decision: Optional[HumanDecisionRequest]

    # ── Final output ──
    final_report: FinalReport

    # ── Metadata ──
    total_duration_ms: int
    llm_token_usage: TokenUsage
    version: str


def create_initial_state(user_input: dict[str, Any]) -> WorkflowState:
    """Factory — creates a fresh WorkflowState from user input."""
    now = datetime.utcnow().isoformat()
    return WorkflowState(
        task_id=str(uuid4()),
        created_at=now,
        updated_at=now,
        user_input=user_input,
        validated_input={},
        current_phase="initialized",
        phase_history=[],
        progress=0.0,
        research_plan=None,
        evidence_bundle={},
        gap_analysis={},
        insights=None,
        strategic_insights={},
        report_document={},
        review_result={},
        clusters=[],
        errors=[],
        retry_counts={},
        stream_events=[],
        human_checkpoints=[],
        pending_human_decision=None,
        final_report=FinalReport(markdown=None, word_url=None, html=None),
        total_duration_ms=0,
        llm_token_usage=TokenUsage(total_prompt_tokens=0, total_completion_tokens=0),
        version="v1",
    )
