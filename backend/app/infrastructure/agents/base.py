"""Abstract base class for all Agents."""

from __future__ import annotations
import json, re

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Generic, TypeVar

from pydantic import BaseModel

from app.config.constants import ErrorCategory, Phase
from app.infrastructure.trace import trace_collector, TraceStatus
from app.infrastructure.trace.snapshot import capture_input_snapshot, capture_output_snapshot

InputT = TypeVar("InputT", bound=BaseModel)
OutputT = TypeVar("OutputT", bound=BaseModel)


@dataclass
class AgentContext:
    """Runtime context passed to every agent invocation."""
    task_id: str
    current_phase: Phase
    retry_count: int = 0
    started_at: datetime = datetime.now()
    phase_entered_at: Optional[str] = None


@dataclass
class AgentResult:
    """Standardized result wrapper for every agent."""
    success: bool
    output: Any = None
    error: dict | None = None
    duration_ms: int = 0
    phase_record: dict | None = None


class BaseAgent(ABC, Generic[InputT, OutputT]):
    """Abstract base agent.

    Every agent must implement:
      - agent_name    → unique identifier
      - phase         → the Phase this agent represents
      - arun()        → async execution entry point
    """

    @property
    @abstractmethod
    def agent_name(self) -> str:
        """Unique agent identifier, e.g. 'gate', 'planner'."""
        ...

    @property
    @abstractmethod
    def phase(self) -> Phase:
        """The Phase this agent corresponds to."""
        ...

    @abstractmethod
    async def arun(
        self,
        ctx: AgentContext,
        input_data: InputT,
    ) -> AgentResult:
        """Execute the agent's core logic.

        Implementations should:
          1. Validate input
          2. Call LLM / Tools (or return mock data)
          3. Return structured output
          4. Handle errors gracefully via AgentResult
        """
        ...

    # ═══════════════════════════════════════════════════
    #  Shared JSON Parser — handles DeepSeek output quirks
    # ═══════════════════════════════════════════════════

    @staticmethod
    def _parse_llm_json(raw: str) -> dict | None:
        """Robust JSON parser for LLM responses.

        Handles common quirks from DeepSeek and other models:
          - Markdown code fences (```, ```json, ```JSON)
          - JavaScript-style unquoted keys ({key: value})
          - Trailing commas
          - Text before/after the JSON block
          - Multiple JSON blocks (picks the largest valid dict)
          - parse_failed sentinel
        """
        if not raw or not raw.strip():
            return None
        text = raw.strip()

        # ── Step 1: strip markdown code fences ──
        code_fence_re = re.compile(r'^```(?:json|JSON)?\s*\n(.*?)\n```\s*$', re.DOTALL)
        m = code_fence_re.match(text)
        if m:
            text = m.group(1).strip()
        else:
            # Partial fences
            if text.startswith("```"):
                text = text.split("\n", 1)[-1]
            if text.endswith("```"):
                text = text.rsplit("```", 1)[0]
            text = text.strip()

        # ── Step 2: find JSON blocks ──
        candidates = []
        # Find all { ... } blocks (non-greedy, balanced)
        for m in re.finditer(r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}', text):
            candidates.append(m.group())

        # Also try greedy match as fallback
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m and m.group() not in candidates:
            candidates.append(m.group())

        # ── Step 3: try to parse each candidate ──
        for cand in candidates:
            result = BaseAgent._try_parse_json_str(cand)
            if result is not None:
                if isinstance(result, dict) and result.get("parse_failed"):
                    return None  # LLM admitted failure
                if isinstance(result, dict):
                    return result

        # ── Step 4: try the entire text ──
        result = BaseAgent._try_parse_json_str(text)
        if result is not None:
            if isinstance(result, dict) and result.get("parse_failed"):
                return None
            if isinstance(result, dict):
                return result

        return None

    @staticmethod
    def _try_parse_json_str(s: str) -> Any | None:
        """Try to parse a string as JSON with multiple fallback strategies."""
        s = s.strip()
        if not s:
            return None

        # Strategy 1: standard JSON
        try:
            return json.loads(s)
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 2: fix trailing commas
        try:
            fixed = re.sub(r',\s*([}\]])', r'\1', s)
            return json.loads(fixed)
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 3: add quotes to unquoted keys (JS-style)
        try:
            # Match unquoted keys: word followed by colon
            js_fixed = re.sub(r'(\s*)(\w+)(\s*):', r'\1"\2"\3:', s)
            return json.loads(js_fixed)
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy 4: unquoted keys + trailing commas
        try:
            fixed = re.sub(r',\s*([}\]])', r'\1', s)
            js_fixed = re.sub(r'(\s*)(\w+)(\s*):', r'\1"\2"\3:', fixed)
            return json.loads(js_fixed)
        except (json.JSONDecodeError, ValueError):
            pass

        return None

    async def aexecute(
        self,
        ctx: AgentContext,
        input_data: InputT,
    ) -> AgentResult:
        """Wrapper with timing, error boundary, phase tracking, and trace."""
        start = datetime.now()

        # --- Trace: agent start ---
        inp = input_data.model_dump() if hasattr(input_data, "model_dump") else str(input_data)
        input_summary = str(inp)[:200]
        trace = trace_collector.start_trace(
            task_id=ctx.task_id,
            stage="agent",
            agent_name=self.agent_name,
            input_summary=input_summary,
            metadata={"input_snapshot": capture_input_snapshot(self.agent_name, input_data)},
        )
        # ---
        try:
            result = await self.arun(ctx, input_data)
            result.duration_ms = int(
                (datetime.now() - start).total_seconds() * 1000
            )
            # Merge (don't overwrite) the agent's own phase_record so that
            # detailed diagnostics (selection_plan, sources_called, etc.)
            # survive into phase_history / traces.
            detail = result.phase_record if isinstance(result.phase_record, dict) else {}
            result.phase_record = {
                "phase": self.phase.value,
                "entered_at": start.isoformat(),
                "duration_ms": result.duration_ms,
                "status": "completed" if result.success else "failed",
            }
            if detail:
                result.phase_record.update(detail)

            # --- Trace: agent end ---
            out = result.output.model_dump() if hasattr(result.output, "model_dump") else str(result.output)
            trace_collector.end_trace(
                trace,
                success=result.success,
                output_summary=str(out)[:300],
                error=(result.error.get("message") if isinstance(result.error, dict) else str(result.error)) if result.error else None,
                metadata={
                    "duration_ms": result.duration_ms,
                    "phase": self.phase.value,
                    "output_snapshot": capture_output_snapshot(self.agent_name, result.output, result.success),
                },
            )
            # ---

            return result
        except Exception as exc:
            elapsed = int((datetime.now() - start).total_seconds() * 1000)
            return AgentResult(
                success=False,
                error={
                    "code": ErrorCategory.LLM_ERROR.value,
                    "message": str(exc),
                    "node": self.agent_name,
                    "timestamp": datetime.now().isoformat(),
                    "retryable": True,
                },
                duration_ms=elapsed,
                phase_record={
                    "phase": self.phase.value,
                    "entered_at": start.isoformat(),
                    "duration_ms": elapsed,
                    "status": "failed",
                    "error": {"code": ErrorCategory.LLM_ERROR.value, "message": str(exc)},
                },
            )

            # --- Trace: agent exception ---
            trace_collector.end_trace(
                trace,
                success=False,
                output_summary=f"Exception: {exc}",
                error=str(exc),
                metadata={
                    "duration_ms": elapsed,
                    "phase": self.phase.value,
                    "output_snapshot": {"success": False, "error": str(exc)[:200]},
                },
            )
            # ---
