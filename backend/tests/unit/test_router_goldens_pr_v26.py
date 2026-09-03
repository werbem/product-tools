"""Router golden-set evaluator (Phase 2 Step 6).

Gates
-----
- ``CRITICAL_ACCURACY``: every ``critical: true`` case must match (100%).
- ``OVERALL_ACCURACY_THRESHOLD``: all cases, default 0.95.

How to add a golden
-------------------
1. Append an object to ``backend/tests/fixtures/router_goldens.json`` ``cases``.
2. Required fields: ``id``, ``message``, ``expect_workflow_type``.
3. Optional: ``critical``, ``notes``, ``intent_override``, ``context.has_prior_task``,
   ``needs_product_confirm``.
4. ``intent_override``: inject a pre-extracted Intent (company / competitors) so
   the set does not call a real LLM. Omit or ``null`` → heuristic minimal Intent.
5. ``context.has_prior_task`` maps to ``ConversationRoutingContext.has_prior_analysis``.
6. Dump first, then freeze ``expect_workflow_type`` against current Router behavior
   (or the safer label if current would mis-start Full). Put rationale in ``notes``.

How to run
----------
::

    cd backend && PYTHONPATH=. python3 -m pytest \\
      tests/unit/test_router_goldens_pr_v26.py \\
      tests/unit/test_router_service_pr_v21.py \\
      tests/unit/test_intent_mapper_routing.py \\
      -q
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext, RoutingDecision
from app.application.services.router_service import RouterService

GOLDENS_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "router_goldens.json"
MIN_CASE_COUNT = 25
OVERALL_ACCURACY_THRESHOLD = 0.95
CRITICAL_ACCURACY = 1.0
WORKFLOW_TYPES = frozenset(
    {
        "competitive_analysis",
        "research",
        "information_query",
        "simple_question",
        "follow_up",
        "out_of_scope",
    }
)


def _load_fixture() -> dict[str, Any]:
    return json.loads(GOLDENS_PATH.read_text(encoding="utf-8"))


def load_golden_cases() -> list[dict[str, Any]]:
    payload = _load_fixture()
    cases = payload["cases"] if isinstance(payload, dict) else payload
    if not isinstance(cases, list):
        raise AssertionError(f"goldens must be a list of cases: {GOLDENS_PATH}")
    return cases


def build_or_override_intent(case: dict[str, Any]) -> IntentUnderstandingResult:
    """Minimal IntentUnderstandingResult; optional override skips a live LLM."""
    message = str(case["message"])
    override = case.get("intent_override") or {}
    if not isinstance(override, dict):
        override = {}
    return IntentUnderstandingResult(
        type=override.get("type") or "competitive_analysis",
        company=override.get("company"),
        competitors=list(override.get("competitors") or []),
        product=override.get("product"),
        objective=override.get("objective"),
        confidence=float(override.get("confidence") or 0.85),
        missing_fields=list(override.get("missing_fields") or []),
        needs_clarification=bool(override.get("needs_clarification") or False),
        clarification_question=override.get("clarification_question"),
        raw_message=override.get("raw_message") or message,
    )


def run_golden(case: dict[str, Any], router: RouterService | None = None) -> RoutingDecision:
    intent = build_or_override_intent(case)
    ctx_raw = case.get("context") or {}
    has_prior = bool(ctx_raw.get("has_prior_task") or ctx_raw.get("has_prior_analysis"))
    ctx = ConversationRoutingContext(has_prior_analysis=has_prior)
    return (router or RouterService()).route(intent, str(case["message"]), ctx)


def _mismatch_line(case: dict[str, Any], decision: RoutingDecision) -> str:
    return (
        f"id={case.get('id')} expect={case.get('expect_workflow_type')} "
        f"actual={decision.workflow_type} reason={decision.reason!r} "
        f"critical={bool(case.get('critical'))} "
        f"message={case.get('message')!r}"
    )


@pytest.fixture(scope="module")
def golden_cases() -> list[dict[str, Any]]:
    return load_golden_cases()


@pytest.fixture(scope="module")
def router() -> RouterService:
    return RouterService()


class TestRouterGoldensMeta:
    def test_fixture_size_and_types(self, golden_cases: list[dict[str, Any]]) -> None:
        assert len(golden_cases) >= MIN_CASE_COUNT, (
            f"need ≥{MIN_CASE_COUNT} goldens, got {len(golden_cases)}"
        )
        ids = [c["id"] for c in golden_cases]
        assert len(ids) == len(set(ids)), "duplicate golden id"
        got_types = {c["expect_workflow_type"] for c in golden_cases}
        missing = WORKFLOW_TYPES - got_types
        assert not missing, f"goldens missing workflow types: {sorted(missing)}"
        for case in golden_cases:
            assert case["expect_workflow_type"] in WORKFLOW_TYPES
            assert str(case["message"]).strip()


class TestRouterGoldensCritical:
    def test_every_critical_case_matches(
        self,
        golden_cases: list[dict[str, Any]],
        router: RouterService,
    ) -> None:
        critical = [c for c in golden_cases if c.get("critical")]
        assert critical, "fixture must include critical cases"
        failures = []
        for case in critical:
            decision = run_golden(case, router)
            if decision.workflow_type != case["expect_workflow_type"]:
                failures.append(_mismatch_line(case, decision))
        if failures:
            pytest.fail(
                f"critical goldens must be {CRITICAL_ACCURACY:.0%} "
                f"({len(critical) - len(failures)}/{len(critical)} passed)\n"
                + "\n".join(failures)
            )


class TestRouterGoldensAccuracy:
    def test_overall_accuracy_threshold(
        self,
        golden_cases: list[dict[str, Any]],
        router: RouterService,
    ) -> None:
        failures: list[str] = []
        by_expect: Counter[str] = Counter()
        by_ok: Counter[str] = Counter()
        for case in golden_cases:
            expect = case["expect_workflow_type"]
            by_expect[expect] += 1
            decision = run_golden(case, router)
            if decision.workflow_type == expect:
                by_ok[expect] += 1
            else:
                failures.append(_mismatch_line(case, decision))
        total = len(golden_cases)
        passed = total - len(failures)
        accuracy = passed / total if total else 0.0
        summary = ", ".join(
            f"{k}={by_ok[k]}/{by_expect[k]}" for k in sorted(by_expect)
        )
        if accuracy < OVERALL_ACCURACY_THRESHOLD:
            pytest.fail(
                f"golden accuracy {accuracy:.2%} < {OVERALL_ACCURACY_THRESHOLD:.0%} "
                f"({passed}/{total}); by type: {summary}\n"
                + "\n".join(failures)
            )
        assert accuracy >= OVERALL_ACCURACY_THRESHOLD
        # Keep a visible one-liner in pytest output on -vv
        print(
            f"\nrouter goldens: {passed}/{total} accuracy={accuracy:.2%} "
            f"(threshold {OVERALL_ACCURACY_THRESHOLD:.0%}); {summary}"
        )
