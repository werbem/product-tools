"""Task Router — maps Intent + message → RoutingDecision (legacy until Phase 5 cutover).

Rules only (no Router LLM). Phase 1 resolve_workflow_kind is LegacyBridge.

Discourse / ask-form patterns live in ``decision_intent_signals`` (Phase 2).
**Phase 5:** Prefer DecisionPlanner + ThinRouter behind ``DECISION_PLANNER_ROUTING``.
Do not add new semantic regex here — extend Intent/Planner instead. This module
remains the production fallback when the flag is ``off`` or the decision stack fails.

Final priority (must stay in this order):
  1. out_of_scope (hard domain exclusions)
  2. follow_up (deixis keywords + soft advice when prior exists)
  3. information_query (recent changes / dynamics)
  4. simple_question (definition / who / one-liner)
  5. unsupported intent → out_of_scope
  6. LegacyBridge (competitive_analysis vs research; EN collect/research → research)
"""

from __future__ import annotations

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import (
    ConversationRoutingContext,
    RoutingDecision,
)
from app.application.services.decision_intent_signals import (
    looks_like_advice_follow_up,
    looks_like_en_collection,
    looks_like_follow_up_deixis,
    looks_like_light_query,
    looks_like_out_of_scope,
    looks_like_simple_question,
)
from app.application.services.intent_mapper import (
    detect_analysis_intent,
    detect_collection_intent,
    resolve_workflow_kind,
)
from app.application.services.intent_entities import looks_like_competitor_listing_query

_NOT_IMPL_TYPES: frozenset[str] = frozenset()


class RouterService:
    """Independent router after Intent Understanding."""

    def route(
        self,
        intent: IntentUnderstandingResult,
        message: str,
        conversation_context: ConversationRoutingContext | None = None,
    ) -> RoutingDecision:
        text = (message or intent.raw_message or "").strip()
        ctx = conversation_context
        has_prior = bool(ctx and ctx.has_prior_analysis)

        has_analysis = detect_analysis_intent(text)
        has_collection = detect_collection_intent(text)

        # 1) OOS
        if looks_like_out_of_scope(text):
            return RoutingDecision(
                workflow_type="out_of_scope",
                confidence=0.95,
                reason="hard_out_of_scope_pattern",
                legacy_workflow_kind=None,
            )

        # 2) follow_up — deixis keywords, or soft advice when prior exists
        if looks_like_follow_up_deixis(text):
            if has_prior:
                return RoutingDecision(
                    workflow_type="follow_up",
                    confidence=0.85,
                    reason="follow_up_with_prior_context",
                    legacy_workflow_kind=None,
                )
            return RoutingDecision(
                workflow_type="follow_up",
                confidence=0.55,
                reason="follow_up_no_prior",
                legacy_workflow_kind=None,
            )

        if (
            has_prior
            and not has_analysis
            and not has_collection
            and looks_like_advice_follow_up(text)
        ):
            return RoutingDecision(
                workflow_type="follow_up",
                confidence=0.8,
                reason="follow_up_advice_with_prior_context",
                legacy_workflow_kind=None,
            )

        # 3) information_query (dynamics)
        if (
            not has_analysis
            and not has_collection
            and looks_like_light_query(text)
        ):
            return RoutingDecision(
                workflow_type="information_query",
                confidence=0.75,
                reason="information_query_signal_no_analysis_or_collection",
                legacy_workflow_kind=None,
            )

        # 4) Competitor-listing Q&A — alone: short answer; with 分析报告: deep launch
        if (
            looks_like_competitor_listing_query(text)
            and not has_collection
            and not has_analysis
        ):
            return RoutingDecision(
                workflow_type="simple_question",
                confidence=0.88,
                reason="competitor_listing_question",
                legacy_workflow_kind=None,
            )

        # 5) simple_question (definition / who / one-liner)
        if (
            not has_analysis
            and not has_collection
            and looks_like_simple_question(text)
        ):
            return RoutingDecision(
                workflow_type="simple_question",
                confidence=0.72,
                reason="simple_question_definition_or_brief",
                legacy_workflow_kind=None,
            )

        # 5b) English collection (avoid LegacyBridge defaulting these to Full)
        if not has_analysis and looks_like_en_collection(text):
            return RoutingDecision(
                workflow_type="research",
                confidence=0.78,
                reason="en_collection_signal",
                legacy_workflow_kind="intelligence_collection",
            )

        # 6) unsupported → OOS (before LegacyBridge default deep)
        if intent.type == "unsupported":
            return RoutingDecision(
                workflow_type="out_of_scope",
                confidence=float(intent.confidence or 0.9),
                reason="intent_unsupported",
                legacy_workflow_kind=None,
            )

        # 6b) Prior context + no launch signal → do not default-open a new Deep.
        if has_prior and not has_analysis and not has_collection:
            return RoutingDecision(
                workflow_type="follow_up",
                confidence=0.72,
                reason="follow_up_prior_without_launch_signal",
                legacy_workflow_kind=None,
            )

        # 7) LegacyBridge
        kind = resolve_workflow_kind(intent, text)
        if kind == "intelligence_collection":
            return RoutingDecision(
                workflow_type="research",
                confidence=float(intent.confidence or 0.85),
                reason="legacy_bridge_intelligence_collection",
                legacy_workflow_kind="intelligence_collection",
            )
        return RoutingDecision(
            workflow_type="competitive_analysis",
            confidence=float(intent.confidence or 0.85),
            reason="legacy_bridge_deep_analysis",
            legacy_workflow_kind="deep_analysis",
        )

    # Back-compat wrappers used by older tests / call sites
    @staticmethod
    def _looks_like_follow_up(text: str) -> bool:
        return looks_like_follow_up_deixis(text)

    @staticmethod
    def _looks_like_advice_follow_up(text: str) -> bool:
        return looks_like_advice_follow_up(text)

    @staticmethod
    def _looks_like_light_query(text: str) -> bool:
        return looks_like_light_query(text)

    @staticmethod
    def _looks_like_simple_question(text: str) -> bool:
        return looks_like_simple_question(text)

    @staticmethod
    def _looks_like_en_collection(text: str) -> bool:
        return looks_like_en_collection(text)

    @staticmethod
    def is_not_implemented(workflow_type: str) -> bool:
        return workflow_type in _NOT_IMPL_TYPES
