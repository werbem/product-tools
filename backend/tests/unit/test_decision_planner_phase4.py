"""Phase 4: DecisionPlanner goldens + no-implicit-deep + shadow."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import DecisionEntities, EntitySlot
from app.application.dto.decision.intent_contract import DecisionIntent
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext
from app.application.services.decision_entity_extractor import DecisionEntityExtractor
from app.application.services.decision_intent_extractor import DecisionIntentExtractor
from app.application.services.decision_planner import (
    DecisionPlanner,
    assert_no_implicit_deep,
    shadow_compare_plan_vs_router_workflow,
)
from app.application.services.router_service import RouterService

PLANNER_GOLDENS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "planner_goldens.json"
)
ROUTER_GOLDENS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "router_goldens.json"
)
SHADOW_AGREE_THRESHOLD = 0.85


def load_planner_cases() -> list[dict[str, Any]]:
    return json.loads(PLANNER_GOLDENS_PATH.read_text(encoding="utf-8"))["cases"]


def _entities_from_case(case: dict[str, Any]) -> DecisionEntities:
    raw = case.get("entities") or {}
    company = raw.get("company")
    product = raw.get("product")
    comps = list(raw.get("competitors") or [])
    return DecisionEntities(
        company=EntitySlot(
            value=company,
            source="message" if company else "unknown",
            confidence=0.8 if company else 0.0,
        ),
        product=EntitySlot(
            value=product,
            source="message" if product else "unknown",
            confidence=0.8 if product else 0.0,
        ),
        competitors=EntitySlot(
            value=comps,
            source="message" if comps else "unknown",
            confidence=0.8 if comps else 0.0,
        ),
        missing_slots=[
            s for s, v in (
                ("company", company),
                ("product", product),
                ("competitors", comps),
            )
            if not v
        ],
    )


def _intent_for_case(
    case: dict[str, Any],
    extractor: DecisionIntentExtractor,
) -> DecisionIntent:
    forced = case.get("force_intent")
    if forced:
        return DecisionIntent(
            task_family=forced["task_family"],
            discourse=forced.get("discourse") or "new",
            ask_subtype=forced.get("ask_subtype"),
            confidence=float(forced.get("confidence") or 0.7),
            raw_message=str(case["message"]),
        )
    return extractor.extract(
        str(case["message"]),
        has_prior=bool(case.get("has_prior")),
    )


@pytest.fixture(scope="module")
def planner() -> DecisionPlanner:
    return DecisionPlanner()


@pytest.fixture(scope="module")
def intent_extractor() -> DecisionIntentExtractor:
    return DecisionIntentExtractor()


@pytest.fixture(scope="module")
def planner_cases() -> list[dict[str, Any]]:
    return load_planner_cases()


class TestPlannerGoldensMeta:
    def test_dual_pair(self, planner_cases: list[dict[str, Any]]) -> None:
        by_id = {c["id"]: c for c in planner_cases}
        a = by_id["plan_follow_up_ops_advice"]
        b = by_id["plan_analyze_explicit_ca_with_prior"]
        assert a["pair_with"] == b["id"]
        assert b["pair_with"] == a["id"]
        assert a.get("forbid_deep") is True
        assert b["expect_execution_mode"].startswith("deep")


class TestPlannerGoldensCritical:
    def test_critical_plans(
        self,
        planner: DecisionPlanner,
        intent_extractor: DecisionIntentExtractor,
        planner_cases: list[dict[str, Any]],
    ) -> None:
        critical = [c for c in planner_cases if c.get("critical")]
        failures: list[str] = []
        for case in critical:
            intent = _intent_for_case(case, intent_extractor)
            ents = _entities_from_case(case)
            ctx = DecisionContext(has_prior_artifact=bool(case.get("has_prior")))
            plan = planner.plan(intent, ents, ctx)
            try:
                assert_no_implicit_deep(plan, intent)
            except AssertionError as exc:
                failures.append(f"{case['id']} invariant: {exc}")
                continue
            if plan.execution_mode != case["expect_execution_mode"]:
                failures.append(
                    f"{case['id']} mode expect={case['expect_execution_mode']} "
                    f"got={plan.execution_mode} reason={plan.reason}"
                )
            if case.get("expect_workflow_type"):
                if plan.workflow_type != case["expect_workflow_type"]:
                    failures.append(
                        f"{case['id']} workflow expect={case['expect_workflow_type']} "
                        f"got={plan.workflow_type}"
                    )
            if "expect_clarification" in case:
                if bool(plan.clarification_required) != bool(case["expect_clarification"]):
                    failures.append(
                        f"{case['id']} clarification expect="
                        f"{case['expect_clarification']} got={plan.clarification_required}"
                    )
            if case.get("expect_reason_contains"):
                if case["expect_reason_contains"] not in (plan.reason or ""):
                    failures.append(
                        f"{case['id']} reason missing {case['expect_reason_contains']!r} "
                        f"got={plan.reason!r}"
                    )
            if case.get("forbid_deep") and plan.execution_mode in (
                "deep_fast",
                "deep_full",
            ):
                failures.append(f"{case['id']} forbid_deep but got {plan.execution_mode}")
            if case.get("expect_step_ops"):
                got_ops = [s.op for s in plan.steps]
                if got_ops != list(case["expect_step_ops"]):
                    failures.append(
                        f"{case['id']} steps expect={case['expect_step_ops']} got={got_ops}"
                    )
        if failures:
            pytest.fail("planner critical goldens failed:\n" + "\n".join(failures))


class TestPlannerInvariants:
    def test_never_default_deep_on_ambiguous(
        self,
        planner: DecisionPlanner,
        intent_extractor: DecisionIntentExtractor,
    ) -> None:
        msg = "随便聊聊吧"
        intent = intent_extractor.extract(msg, has_prior=False)
        ents = DecisionEntities()
        plan = planner.plan(intent, ents, DecisionContext())
        assert plan.execution_mode not in ("deep_fast", "deep_full")
        assert_no_implicit_deep(plan, intent)

    def test_end_to_end_intent_entity_plan_ops_advice(self) -> None:
        msg = "如果我是产品运营，我下一步应该做什么，推进用户体验和稳固产品壁垒？"
        intent = DecisionIntentExtractor().extract(msg, has_prior=True)
        ents = DecisionEntityExtractor().extract(
            msg,
            prior_company="滴滴出行",
            prior_product="滴滴打车",
            prior_competitors=["高德打车", "曹操出行"],
        )
        plan = DecisionPlanner().plan(
            intent,
            ents,
            DecisionContext(has_prior_artifact=True),
        )
        assert intent.task_family == "advise_prior"
        assert plan.execution_mode == "follow_up"
        assert_no_implicit_deep(plan, intent)


class TestPlannerShadowVsRouter:
    def test_shadow_agreement_floor(self) -> None:
        router_cases = json.loads(ROUTER_GOLDENS_PATH.read_text(encoding="utf-8"))["cases"]
        intent_ex = DecisionIntentExtractor()
        entity_ex = DecisionEntityExtractor()
        planner = DecisionPlanner()
        router = RouterService()
        agree = 0
        total = 0
        mismatches: list[str] = []
        for case in router_cases:
            total += 1
            message = str(case["message"])
            has_prior = bool((case.get("context") or {}).get("has_prior_task"))
            override = case.get("intent_override") or {}
            if not isinstance(override, dict):
                override = {}
            legacy = IntentUnderstandingResult(
                type=override.get("type") or "competitive_analysis",
                company=override.get("company"),
                competitors=list(override.get("competitors") or []),
                product=override.get("product"),
                objective=override.get("objective"),
                confidence=float(override.get("confidence") or 0.85),
                raw_message=message,
            )
            intent = intent_ex.extract(message, has_prior=has_prior)
            ents = entity_ex.extract(
                message,
                legacy_intent=legacy,
                prior_company=legacy.company if has_prior else None,
                prior_product=legacy.product if has_prior else None,
                prior_competitors=list(legacy.competitors or []) if has_prior else None,
            )
            plan = planner.plan(
                intent,
                ents,
                DecisionContext(has_prior_artifact=has_prior),
            )
            rd = router.route(
                legacy,
                message,
                ConversationRoutingContext(has_prior_analysis=has_prior),
            )
            cmp = shadow_compare_plan_vs_router_workflow(
                plan=plan,
                router_workflow_type=rd.workflow_type,
            )
            if cmp["agree"]:
                agree += 1
            else:
                mismatches.append(
                    f"{case['id']} mode={plan.execution_mode} reason={plan.reason} "
                    f"router={rd.workflow_type}/{rd.reason} family={intent.task_family}"
                )
        rate = agree / total if total else 0.0
        if rate < SHADOW_AGREE_THRESHOLD:
            pytest.fail(
                f"planner shadow agree {rate:.2%} < {SHADOW_AGREE_THRESHOLD:.0%} "
                f"({agree}/{total})\n" + "\n".join(mismatches[:25])
            )
        assert rate >= SHADOW_AGREE_THRESHOLD
