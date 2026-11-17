"""Decision-stack E2E eval helpers (Phase 7).

Runs Intent → Entity → Planner → ThinRouter offline against goldens.
Does not change production routing (default remains off).
"""

from __future__ import annotations

from typing import Any

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.decision_routing import run_decision_stack


REQUIRED_E2E_SLICES = frozenset(
    {
        "ca_launch",
        "research",
        "listing",
        "qa",
        "follow_up_short",
        "follow_up_upgrade",
        "clarify",
        "invalid_deixis",
        "memory_fill",
        "multi_step",
        "oos",
        "ambiguous",
    }
)


def build_legacy_intent(case: dict[str, Any]) -> IntentUnderstandingResult:
    message = str(case["message"])
    override = case.get("intent_override") or case.get("legacy_intent") or {}
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
        raw_message=message,
    )


def evaluate_e2e_case(case: dict[str, Any]) -> dict[str, Any]:
    """Run one golden through the decision stack; return scored result."""
    message = str(case["message"])
    has_prior = bool(case.get("has_prior"))
    memory = case.get("memory")
    legacy = build_legacy_intent(case)
    intent, ents, cap = run_decision_stack(
        message=message,
        legacy_intent=legacy,
        has_prior=has_prior,
        memory=memory,
        analysis_mode_hint=case.get("analysis_mode_hint"),
    )
    plan = cap.plan
    step_ops = [s.op for s in plan.steps]
    failures: list[str] = []

    if case.get("expect_task_family") is not None:
        if intent.task_family != case["expect_task_family"]:
            failures.append(
                f"task_family expect={case['expect_task_family']} got={intent.task_family}"
            )

    if case.get("expect_discourse") is not None:
        if intent.discourse != case["expect_discourse"]:
            failures.append(
                f"discourse expect={case['expect_discourse']} got={intent.discourse}"
            )

    if case.get("expect_execution_mode") is not None:
        if plan.execution_mode != case["expect_execution_mode"]:
            failures.append(
                f"execution_mode expect={case['expect_execution_mode']} "
                f"got={plan.execution_mode}"
            )

    if case.get("expect_workflow_type") is not None:
        if plan.workflow_type != case["expect_workflow_type"]:
            failures.append(
                f"workflow_type expect={case['expect_workflow_type']} "
                f"got={plan.workflow_type}"
            )

    if case.get("expect_capability") is not None:
        if cap.capability != case["expect_capability"]:
            failures.append(
                f"capability expect={case['expect_capability']} got={cap.capability}"
            )

    if "expect_clarification" in case:
        want = bool(case["expect_clarification"])
        if bool(plan.clarification_required) != want:
            failures.append(
                f"clarification expect={want} got={plan.clarification_required}"
            )

    if case.get("expect_reason_contains"):
        needle = str(case["expect_reason_contains"])
        if needle not in (plan.reason or ""):
            failures.append(f"reason missing {needle!r} got={plan.reason!r}")

    if case.get("expect_step_ops") is not None:
        want_ops = list(case["expect_step_ops"])
        if step_ops != want_ops:
            failures.append(f"step_ops expect={want_ops} got={step_ops}")

    if "expect_company" in case:
        got_co = ents.company_name()
        want_co = case["expect_company"]
        if got_co != want_co:
            failures.append(f"company expect={want_co!r} got={got_co!r}")

    if case.get("expect_company_source"):
        if ents.company.source != case["expect_company_source"]:
            failures.append(
                f"company_source expect={case['expect_company_source']} "
                f"got={ents.company.source}"
            )

    if case.get("forbid_deep") and plan.execution_mode in ("deep_fast", "deep_full"):
        failures.append(f"forbid_deep but got {plan.execution_mode}")

    if case.get("forbid_capability"):
        if cap.capability == case["forbid_capability"]:
            failures.append(f"forbid_capability={case['forbid_capability']}")

    return {
        "id": case.get("id"),
        "passed": not failures,
        "failures": failures,
        "task_family": intent.task_family,
        "discourse": intent.discourse,
        "execution_mode": plan.execution_mode,
        "workflow_type": plan.workflow_type,
        "capability": cap.capability,
        "reason": plan.reason,
        "step_ops": step_ops,
        "clarification_required": plan.clarification_required,
        "company": ents.company_name(),
        "company_source": ents.company.source,
        "product": ents.product_name(),
        "critical": bool(case.get("critical")),
        "slice": case.get("slice"),
    }


def evaluate_e2e_suite(cases: list[dict[str, Any]]) -> dict[str, Any]:
    """Score full suite; compute critical/overall accuracy."""
    results = [evaluate_e2e_case(c) for c in cases]
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    critical = [r for r in results if r["critical"]]
    critical_passed = sum(1 for r in critical if r["passed"])
    critical_total = len(critical)
    overall = (passed / total) if total else 0.0
    critical_acc = (critical_passed / critical_total) if critical_total else 1.0
    by_slice: dict[str, dict[str, int]] = {}
    for r in results:
        sl = str(r.get("slice") or "unknown")
        bucket = by_slice.setdefault(sl, {"total": 0, "passed": 0})
        bucket["total"] += 1
        if r["passed"]:
            bucket["passed"] += 1
    return {
        "case_count": total,
        "passed": passed,
        "failed": total - passed,
        "overall_accuracy": overall,
        "critical_count": critical_total,
        "critical_passed": critical_passed,
        "critical_accuracy": critical_acc,
        "by_slice": by_slice,
        "failures": [
            {"id": r["id"], "failures": r["failures"], "got": {
                "execution_mode": r["execution_mode"],
                "workflow_type": r["workflow_type"],
                "capability": r["capability"],
                "reason": r["reason"],
                "company": r["company"],
            }}
            for r in results
            if not r["passed"]
        ],
        "results": results,
    }
