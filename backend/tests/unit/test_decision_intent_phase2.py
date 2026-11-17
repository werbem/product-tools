"""Phase 2: DecisionIntentExtractor goldens + shadow compare."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext
from app.application.services.decision_intent_extractor import (
    DecisionIntentExtractor,
    shadow_compare_intent_vs_router_workflow,
)
from app.application.services.router_service import RouterService

INTENT_GOLDENS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "intent_goldens.json"
)
ROUTER_GOLDENS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "router_goldens.json"
)
MIN_CASE_COUNT = 20
CRITICAL_ACCURACY = 1.0
OVERALL_ACCURACY_THRESHOLD = 0.95
SHADOW_AGREE_THRESHOLD = 0.90


def load_intent_cases() -> list[dict[str, Any]]:
    payload = json.loads(INTENT_GOLDENS_PATH.read_text(encoding="utf-8"))
    cases = payload["cases"]
    assert isinstance(cases, list)
    return cases


@pytest.fixture(scope="module")
def intent_cases() -> list[dict[str, Any]]:
    return load_intent_cases()


@pytest.fixture(scope="module")
def extractor() -> DecisionIntentExtractor:
    return DecisionIntentExtractor()


class TestIntentGoldensMeta:
    def test_size_and_ids(self, intent_cases: list[dict[str, Any]]) -> None:
        assert len(intent_cases) >= MIN_CASE_COUNT
        ids = [c["id"] for c in intent_cases]
        assert len(ids) == len(set(ids))
        for case in intent_cases:
            assert case.get("expect_task_family")
            assert case.get("expect_discourse")
            assert str(case.get("message") or "").strip()

    def test_dual_pair_present(self, intent_cases: list[dict[str, Any]]) -> None:
        by_id = {c["id"]: c for c in intent_cases}
        assert "fu_ops_advice_no_deixis" in by_id
        assert "ca_explicit_with_prior_still_deep" in by_id
        a = by_id["fu_ops_advice_no_deixis"]
        b = by_id["ca_explicit_with_prior_still_deep"]
        assert a["expect_task_family"] == "advise_prior"
        assert b["expect_task_family"] == "analyze"
        assert a.get("pair_with") == b["id"]
        assert b.get("pair_with") == a["id"]


class TestIntentGoldensCritical:
    def test_critical_task_family_and_discourse(
        self,
        intent_cases: list[dict[str, Any]],
        extractor: DecisionIntentExtractor,
    ) -> None:
        critical = [c for c in intent_cases if c.get("critical")]
        assert critical
        failures: list[str] = []
        for case in critical:
            got = extractor.extract(
                str(case["message"]),
                has_prior=bool(case.get("has_prior")),
            )
            if got.task_family != case["expect_task_family"]:
                failures.append(
                    f"{case['id']} family expect={case['expect_task_family']} "
                    f"got={got.task_family}"
                )
            if got.discourse != case["expect_discourse"]:
                failures.append(
                    f"{case['id']} discourse expect={case['expect_discourse']} "
                    f"got={got.discourse}"
                )
            expect_sub = case.get("expect_ask_subtype")
            if expect_sub is not None and got.ask_subtype != expect_sub:
                failures.append(
                    f"{case['id']} subtype expect={expect_sub} got={got.ask_subtype}"
                )
        if failures:
            pytest.fail(
                f"critical intent goldens must be {CRITICAL_ACCURACY:.0%}\n"
                + "\n".join(failures)
            )


class TestIntentGoldensAccuracy:
    def test_overall_accuracy(
        self,
        intent_cases: list[dict[str, Any]],
        extractor: DecisionIntentExtractor,
    ) -> None:
        failures: list[str] = []
        by_family: Counter[str] = Counter()
        ok_family: Counter[str] = Counter()
        for case in intent_cases:
            fam = case["expect_task_family"]
            by_family[fam] += 1
            got = extractor.extract(
                str(case["message"]),
                has_prior=bool(case.get("has_prior")),
            )
            family_ok = got.task_family == fam
            discourse_ok = got.discourse == case["expect_discourse"]
            sub = case.get("expect_ask_subtype")
            subtype_ok = sub is None or got.ask_subtype == sub
            if family_ok and discourse_ok and subtype_ok:
                ok_family[fam] += 1
            else:
                failures.append(
                    f"id={case['id']} expect=({fam},{case['expect_discourse']},{sub}) "
                    f"got=({got.task_family},{got.discourse},{got.ask_subtype})"
                )
        total = len(intent_cases)
        passed = total - len(failures)
        accuracy = passed / total if total else 0.0
        if accuracy < OVERALL_ACCURACY_THRESHOLD:
            pytest.fail(
                f"intent golden accuracy {accuracy:.2%} < "
                f"{OVERALL_ACCURACY_THRESHOLD:.0%} ({passed}/{total})\n"
                + "\n".join(failures)
            )
        assert accuracy >= OVERALL_ACCURACY_THRESHOLD


class TestIntentShadowVsRouter:
    def test_shadow_agreement_floor(self) -> None:
        """Phase 2 shadow: Intent family vs production Router workflow buckets."""
        router_cases = json.loads(ROUTER_GOLDENS_PATH.read_text(encoding="utf-8"))["cases"]
        extractor = DecisionIntentExtractor()
        router = RouterService()
        agree = 0
        total = 0
        mismatches: list[str] = []
        for case in router_cases:
            total += 1
            message = str(case["message"])
            has_prior = bool((case.get("context") or {}).get("has_prior_task"))
            intent_override = case.get("intent_override") or {}
            if not isinstance(intent_override, dict):
                intent_override = {}
            legacy = IntentUnderstandingResult(
                type=intent_override.get("type") or "competitive_analysis",
                company=intent_override.get("company"),
                competitors=list(intent_override.get("competitors") or []),
                product=intent_override.get("product"),
                objective=intent_override.get("objective"),
                confidence=float(intent_override.get("confidence") or 0.85),
                raw_message=message,
            )
            decision = extractor.extract(message, has_prior=has_prior)
            rd = router.route(
                legacy,
                message,
                ConversationRoutingContext(has_prior_analysis=has_prior),
            )
            cmp = shadow_compare_intent_vs_router_workflow(
                decision_intent=decision,
                router_workflow_type=rd.workflow_type,
            )
            if cmp["agree"]:
                agree += 1
            else:
                mismatches.append(
                    f"{case['id']} family={decision.task_family} "
                    f"router={rd.workflow_type} reason={rd.reason}"
                )
        rate = agree / total if total else 0.0
        if rate < SHADOW_AGREE_THRESHOLD:
            pytest.fail(
                f"shadow agree {rate:.2%} < {SHADOW_AGREE_THRESHOLD:.0%} "
                f"({agree}/{total})\n" + "\n".join(mismatches[:20])
            )
        assert rate >= SHADOW_AGREE_THRESHOLD


class TestDecisionIntentExtractorUnit:
    def test_ops_advice_no_deixis(self, extractor: DecisionIntentExtractor) -> None:
        raw = "如果我是产品运营，我下一步应该做什么，推进用户体验和稳固产品壁垒？"
        got = extractor.extract(raw, has_prior=True)
        assert got.task_family == "advise_prior"
        assert got.discourse == "continue_prior"
        assert got.ask_subtype == "advice"

    def test_explicit_ca_with_prior(self, extractor: DecisionIntentExtractor) -> None:
        raw = "帮我做滴滴出行和曹操出行的竞品分析报告"
        got = extractor.extract(raw, has_prior=True)
        assert got.task_family == "analyze"
        assert got.discourse == "new"

    def test_no_implicit_analyze_without_signals(
        self,
        extractor: DecisionIntentExtractor,
    ) -> None:
        got = extractor.extract("随便聊聊吧", has_prior=False)
        assert got.task_family == "ask"
        assert got.ask_subtype == "other"
        assert got.confidence <= 0.5
