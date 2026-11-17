"""Phase 3: DecisionEntityExtractor goldens + invariants."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import ConversationRoutingContext
from app.application.services.decision_entity_extractor import (
    DecisionEntityExtractor,
    entities_imply_launch,
)
from app.application.services.decision_intent_extractor import DecisionIntentExtractor
from app.application.services.router_service import RouterService

ENTITY_GOLDENS_PATH = (
    Path(__file__).resolve().parent.parent / "fixtures" / "entity_goldens.json"
)


def load_entity_cases() -> list[dict[str, Any]]:
    return json.loads(ENTITY_GOLDENS_PATH.read_text(encoding="utf-8"))["cases"]


def _legacy_from_case(case: dict[str, Any]) -> IntentUnderstandingResult | None:
    raw = case.get("legacy_intent")
    if not raw:
        return None
    return IntentUnderstandingResult(
        type="competitive_analysis",
        company=raw.get("company"),
        competitors=list(raw.get("competitors") or []),
        product=raw.get("product"),
        confidence=0.85,
        raw_message=str(case["message"]),
    )


@pytest.fixture(scope="module")
def extractor() -> DecisionEntityExtractor:
    return DecisionEntityExtractor()


@pytest.fixture(scope="module")
def entity_cases() -> list[dict[str, Any]]:
    return load_entity_cases()


class TestEntityGoldens:
    def test_critical_cases(
        self,
        extractor: DecisionEntityExtractor,
        entity_cases: list[dict[str, Any]],
    ) -> None:
        critical = [c for c in entity_cases if c.get("critical")]
        assert critical
        failures: list[str] = []
        for case in critical:
            prior = case.get("prior") or {}
            got = extractor.extract(
                str(case["message"]),
                legacy_intent=_legacy_from_case(case),
                memory=case.get("memory"),
                prior_company=prior.get("company"),
                prior_product=prior.get("product"),
                prior_competitors=list(prior.get("competitors") or []),
            )
            if "expect_company" in case:
                expected = case["expect_company"]
                actual = got.company_name()
                if expected is None:
                    if actual is not None:
                        failures.append(
                            f"{case['id']} company expect=None got={actual!r}"
                        )
                elif actual != expected:
                    failures.append(
                        f"{case['id']} company expect={expected!r} got={actual!r}"
                    )
            if case.get("expect_company_source"):
                if got.company.source != case["expect_company_source"]:
                    # When value is None, source is unknown
                    if not (
                        case["expect_company"] is None
                        and got.company.source == "unknown"
                    ):
                        failures.append(
                            f"{case['id']} company.source expect="
                            f"{case['expect_company_source']} got={got.company.source}"
                        )
            if case.get("expect_product"):
                if got.product_name() != case["expect_product"]:
                    failures.append(
                        f"{case['id']} product expect={case['expect_product']!r} "
                        f"got={got.product_name()!r}"
                    )
            if case.get("expect_product_source"):
                if got.product.source != case["expect_product_source"]:
                    failures.append(
                        f"{case['id']} product.source expect="
                        f"{case['expect_product_source']} got={got.product.source}"
                    )
            contains = case.get("expect_competitors_contains") or []
            comps = got.competitor_names()
            for name in contains:
                if name not in comps:
                    failures.append(
                        f"{case['id']} missing competitor {name!r} in {comps}"
                    )
            assert entities_imply_launch(got) is False
        if failures:
            pytest.fail("critical entity goldens failed:\n" + "\n".join(failures))

    def test_all_cases_smoke(
        self,
        extractor: DecisionEntityExtractor,
        entity_cases: list[dict[str, Any]],
    ) -> None:
        for case in entity_cases:
            prior = case.get("prior") or {}
            got = extractor.extract(
                str(case["message"]),
                legacy_intent=_legacy_from_case(case),
                memory=case.get("memory"),
                prior_company=prior.get("company"),
                prior_product=prior.get("product"),
                prior_competitors=list(prior.get("competitors") or []),
            )
            if case.get("expect_competitors_min"):
                assert len(got.competitor_names()) >= int(case["expect_competitors_min"])
            if case.get("expect_competitors_source_in"):
                assert got.competitors.source in set(case["expect_competitors_source_in"])
            if case.get("expect_time_range_contains"):
                tr = got.time_range.value
                assert isinstance(tr, str) and case["expect_time_range_contains"] in tr
            assert entities_imply_launch(got) is False


class TestEntityInvariants:
    def test_never_implies_launch(self, extractor: DecisionEntityExtractor) -> None:
        ents = extractor.extract(
            "帮我做滴滴出行和曹操出行的竞品分析报告",
            legacy_intent=IntentUnderstandingResult(
                type="competitive_analysis",
                company="滴滴出行",
                competitors=["曹操出行"],
                product="滴滴打车",
                confidence=0.9,
                raw_message="帮我做滴滴出行和曹操出行的竞品分析报告",
            ),
        )
        assert ents.company_name() == "滴滴出行"
        assert ents.competitor_names()
        assert entities_imply_launch(ents) is False

    def test_no_router_side_effect_on_extract(self, extractor: DecisionEntityExtractor) -> None:
        """Entity extract must not depend on Router / change routing."""
        msg = "如果我是产品运营，我下一步应该做什么，推进用户体验和稳固产品壁垒？"
        before = RouterService().route(
            IntentUnderstandingResult(
                type="competitive_analysis",
                company="滴滴出行",
                competitors=["高德打车"],
                product="滴滴打车",
                confidence=0.9,
                raw_message=msg,
            ),
            msg,
            ConversationRoutingContext(has_prior_analysis=True),
        )
        extractor.extract(
            msg,
            prior_company="滴滴出行",
            prior_product="滴滴打车",
            memory={
                "entities": {
                    "our_company": "滴滴出行",
                    "product": "滴滴打车",
                    "competitors": ["高德打车"],
                }
            },
        )
        after = RouterService().route(
            IntentUnderstandingResult(
                type="competitive_analysis",
                company="滴滴出行",
                competitors=["高德打车"],
                product="滴滴打车",
                confidence=0.9,
                raw_message=msg,
            ),
            msg,
            ConversationRoutingContext(has_prior_analysis=True),
        )
        assert before.workflow_type == after.workflow_type == "follow_up"

    def test_intent_plus_entity_pipeline_smoke(self) -> None:
        intent_ex = DecisionIntentExtractor()
        entity_ex = DecisionEntityExtractor()
        msg = "它都有哪些竞品？"
        intent = intent_ex.extract(msg, has_prior=True)
        ents = entity_ex.extract(
            msg,
            prior_company="滴滴出行",
            prior_product="滴滴打车",
        )
        assert intent.task_family in {"ask", "advise_prior"}
        assert ents.company_name() == "滴滴出行"
        assert ents.company.source == "prior"
        ctx = DecisionContext(
            has_prior_artifact=True,
            memory_company="滴滴出行",
            memory_product="滴滴打车",
        )
        assert ctx.has_prior_artifact is True
