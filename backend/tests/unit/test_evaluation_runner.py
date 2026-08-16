"""Unit tests for the MCP evaluation runner."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.runner.case_loader import load_case, load_cases
from evaluation.runner.response_validation import validate_response
from evaluation.runner.runner import EvaluationRunner


REPO_ROOT = Path(__file__).resolve().parents[3]


class CaseLoaderTest(unittest.TestCase):
    def test_loads_all_benchmark_cases(self) -> None:
        cases = load_cases(REPO_ROOT / "evaluation" / "cases")
        self.assertGreaterEqual(len(cases), 5)
        self.assertEqual(cases[0]["case_id"], "case_001_standard_analysis")

    def test_load_case_contains_expected_fields(self) -> None:
        case = load_case(
            REPO_ROOT / "evaluation" / "cases" / "case_001_standard_analysis.json"
        )
        self.assertIn("input", case)
        self.assertIn("expected", case)
        self.assertIn("required_dimensions", case["expected"])


class ResponseValidationTest(unittest.TestCase):
    def test_valid_collect_response(self) -> None:
        response = {
            "schema_version": "1.0",
            "status": "completed",
            "evidenceItem": [],
            "coverage": {},
        }
        self.assertEqual(validate_response("collect", response), [])

    def test_invalid_analyze_response(self) -> None:
        response = {"summary": "x"}
        self.assertIn("recommendations", validate_response("analyze", response))


class EvaluationRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_runner_writes_result_for_mock_response(self) -> None:
        class MockInvoker:
            async def invoke(self, case):
                return {
                    "schema_version": "1.0",
                    "status": "completed",
                    "evidenceItem": [],
                    "coverage": {},
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            case_dir = root / "cases"
            result_dir = root / "results"
            case_dir.mkdir()
            (case_dir / "case_001.json").write_text(
                json.dumps(
                    {
                        "case_id": "case_001",
                        "tool": "collect",
                        "input": {
                            "our_company": "A",
                            "competitor_company": "B",
                            "product": "C",
                        },
                    }
                ),
                encoding="utf-8",
            )

            runner = EvaluationRunner(
                case_dir=case_dir,
                result_dir=result_dir,
                tool_invoker=MockInvoker(),
            )
            results = await runner.run_all()

            self.assertEqual(results[0]["status"], "passed")
            self.assertTrue((result_dir / "case_001.json").exists())


if __name__ == "__main__":
    unittest.main()
