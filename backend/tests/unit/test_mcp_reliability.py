"""Unit tests for MCP service-level reliability helpers."""

from __future__ import annotations

import sys
import unittest
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.interfaces.mcp.adapters.reliability import run_with_retry
from app.interfaces.mcp.errors import MCPErrorCode
from app.interfaces.mcp.schemas import (
    AnalyzeCompetitionOutput,
    CollectCompetitorIntelligenceInput,
    CollectCompetitorIntelligenceOutput,
    CompanyContext,
)
from tests.integration.test_mcp_runtime import FakeFastMCP, _fake_mcp_modules


class RetryHelperTest(unittest.IsolatedAsyncioTestCase):
    async def test_retry_succeeds_after_temporary_error(self) -> None:
        calls = 0

        async def flaky():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("temporary")
            return "ok"

        result = await run_with_retry(flaky, attempts=2)
        self.assertEqual(result, "ok")
        self.assertEqual(calls, 2)

    async def test_retry_exhausted_raises(self) -> None:
        async def always_timeout():
            raise TimeoutError("timeout")

        with self.assertRaises(TimeoutError):
            await run_with_retry(always_timeout, attempts=2)

    async def test_validation_error_is_not_retried(self) -> None:
        calls = 0

        async def invalid():
            nonlocal calls
            calls += 1
            raise ValidationError.from_exception_data(
                "AnalyzeCompetitionInput",
                [{"type": "missing", "loc": ("product",)}],
            )

        with self.assertRaises(ValidationError):
            await run_with_retry(invalid, attempts=3)
        self.assertEqual(calls, 1)


class ErrorContractTest(unittest.TestCase):
    def test_collect_error_contract(self) -> None:
        output = CollectCompetitorIntelligenceOutput(
            collection_id="id",
            status="failed",
            error_code=MCPErrorCode.COLLECT_VALIDATION_FAILED.value,
            message="invalid input",
            companies=CompanyContext(
                our_company="A",
                competitor_company="B",
                product="C",
            ),
        )
        self.assertEqual(output.status, "failed")
        self.assertEqual(output.error_code, "COLLECT_VALIDATION_FAILED")
        self.assertEqual(output.message, "invalid input")

    def test_analyze_error_contract(self) -> None:
        output = AnalyzeCompetitionOutput(
            status="failed",
            error_code=MCPErrorCode.ANALYSIS_TIMEOUT.value,
            message="analysis timed out",
        )
        self.assertEqual(output.status, "failed")
        self.assertEqual(output.error_code, "ANALYSIS_TIMEOUT")
        self.assertEqual(output.message, "analysis timed out")


class MCPTimeoutContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self._patcher = patch.dict(sys.modules, _fake_mcp_modules())
        self._patcher.start()
        from app.interfaces.mcp.server import create_mcp_server

        self.server = create_mcp_server()

    def tearDown(self) -> None:
        self._patcher.stop()

    async def test_collect_timeout_returns_error_contract(self) -> None:
        import app.interfaces.mcp.tools.collect_intelligence_tool as collect_module

        with patch.object(
            collect_module.WorkflowRunner,
            "run_collect",
            new=AsyncMock(side_effect=TimeoutError("collect timeout")),
        ):
            result = await self.server.call_tool(
                "collect_competitor_intelligence",
                CollectCompetitorIntelligenceInput(
                    our_company="A",
                    competitor_company="B",
                    product="C",
                ),
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error_code, MCPErrorCode.COLLECT_TIMEOUT.value)
        self.assertIn("collect timeout", result.message)


if __name__ == "__main__":
    unittest.main()
