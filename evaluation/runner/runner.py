"""Run evaluation cases and persist results."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from evaluation.runner.case_loader import load_cases
from evaluation.runner.response_validation import validate_response
from evaluation.runner.result_store import ResultStore
from evaluation.runner.tool_invoker import DirectToolInvoker


class EvaluationRunner:
    def __init__(
        self,
        case_dir: Path,
        result_dir: Path,
        tool_invoker: Any | None = None,
    ) -> None:
        self.case_dir = case_dir
        self.result_store = ResultStore(result_dir)
        self.tool_invoker = tool_invoker or DirectToolInvoker()

    async def run_case(self, case: dict[str, Any]) -> dict[str, Any]:
        case_id = case["case_id"]
        started = time.perf_counter()

        try:
            output = await self.tool_invoker.invoke(case)
            missing = validate_response(case.get("tool", ""), output)
            status = "passed" if not missing else "failed"
        except Exception as exc:
            output = {"error": f"{type(exc).__name__}: {exc}"}
            missing = ["execution_error"]
            status = "failed"

        execution_time = round((time.perf_counter() - started) * 1000, 2)
        result = {
            "case_id": case_id,
            "tool": case.get("tool", ""),
            "input": case.get("input", {}),
            "expected": case.get("expected", {}),
            "output": output,
            "execution_time": execution_time,
            "status": status,
            "missing_fields": missing,
        }
        self.result_store.save(case_id, result)
        return result

    async def run_all(self) -> list[dict[str, Any]]:
        return [await self.run_case(case) for case in load_cases(self.case_dir)]
