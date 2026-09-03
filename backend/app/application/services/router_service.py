"""Task Router — maps Intent + message → RoutingDecision (Phase 2).

Rules only (no Router LLM). Phase 1 resolve_workflow_kind is LegacyBridge.

Final priority (must stay in this order):
  1. out_of_scope (hard domain exclusions)
  2. follow_up
  3. information_query (recent changes / dynamics)
  4. simple_question (definition / who / one-liner)
  5. unsupported intent → out_of_scope
  6. LegacyBridge (competitive_analysis vs research; EN collect/research → research)
"""

from __future__ import annotations

import re

from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.dto.routing_dto import (
    ConversationRoutingContext,
    RoutingDecision,
)
from app.application.services.intent_mapper import (
    detect_analysis_intent,
    detect_collection_intent,
    resolve_workflow_kind,
)

# Hard out-of-domain
_OUT_OF_SCOPE_PATTERN = re.compile(
    r"天气|气温|下雨|几点|几点钟|星座|彩票|做饭|菜谱|"
    r"请假邮件|写.{0,8}请假|"
    r"how'?s\s+the\s+weather|what\s+time\s+is\s+it",
    re.IGNORECASE,
)

_FOLLOW_UP_PATTERN = re.compile(
    r"基于刚才|根据上次|继续分析|接着刚才|补充一下|在此基础上|"
    r"刚才的报告|上一份|上一次|刚才的结果|基于上次|接着看|"
    r"继续[，,、]?把|"
    r"继续.{0,32}(?:完整(?:竞品分析)?报告|出报告|全面对比)|"
    r"based on (?:the )?(?:last|previous)|follow[\s-]?up|continue from",
    re.IGNORECASE,
)

# Dynamics / recent-change questions (stronger than simple definition)
_LIGHT_QUERY_PATTERN = re.compile(
    r"(?:最近|近期).{0,16}(?:有什么|有哪些|什么变化|变化|动态|近况|新功能)|"
    r"(?:有什么变化|什么情况|近况如何|怎么样了|有哪些新功能)|"
    r"what(?:'s|\s+is)\s+new|recent\s+changes|what(?:'s|\s+is)\s+happening",
    re.IGNORECASE,
)

# Definition / identity / brief explainers
_SIMPLE_QUESTION_PATTERN = re.compile(
    r"(?:是什么|是谁|什么意思|简单介绍|一句话|简要介绍|介绍一下)|"
    r"(?:大概是怎样|是怎样的|有哪些类型)|"
    r"(?:注意点|注意事项|要注意什么|有什么注意)|"
    r"(?:有哪些竞品|对比了哪些竞品|竞品是谁)|"
    r"(?:吗？|吗\?)\s*$|"
    r"what\s+is|who\s+is|which\s+competitors|briefly|in\s+one\s+sentence",
    re.IGNORECASE,
)

# English collect/research phrasing (Chinese 收集/调研 is LegacyBridge)
_EN_COLLECTION_PATTERN = re.compile(
    r"\b(?:collect|gather|research)\b.{0,48}"
    r"\b(?:info|information|intel|news|materials?|data)\b",
    re.IGNORECASE,
)

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
        if _OUT_OF_SCOPE_PATTERN.search(text):
            return RoutingDecision(
                workflow_type="out_of_scope",
                confidence=0.95,
                reason="hard_out_of_scope_pattern",
                legacy_workflow_kind=None,
            )

        # 2) follow_up
        if self._looks_like_follow_up(text):
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

        # 3) information_query (dynamics)
        if (
            not has_analysis
            and not has_collection
            and self._looks_like_light_query(text)
        ):
            return RoutingDecision(
                workflow_type="information_query",
                confidence=0.75,
                reason="information_query_signal_no_analysis_or_collection",
                legacy_workflow_kind=None,
            )

        # 4) simple_question (definition / who / one-liner)
        if (
            not has_analysis
            and not has_collection
            and self._looks_like_simple_question(text)
        ):
            return RoutingDecision(
                workflow_type="simple_question",
                confidence=0.72,
                reason="simple_question_definition_or_brief",
                legacy_workflow_kind=None,
            )

        # 4b) English collection (avoid LegacyBridge defaulting these to Full)
        if not has_analysis and self._looks_like_en_collection(text):
            return RoutingDecision(
                workflow_type="research",
                confidence=0.78,
                reason="en_collection_signal",
                legacy_workflow_kind="intelligence_collection",
            )

        # 5) unsupported → OOS (before LegacyBridge default deep)
        if intent.type == "unsupported":
            return RoutingDecision(
                workflow_type="out_of_scope",
                confidence=float(intent.confidence or 0.9),
                reason="intent_unsupported",
                legacy_workflow_kind=None,
            )

        # 6) LegacyBridge
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

    @staticmethod
    def _looks_like_follow_up(text: str) -> bool:
        if not text:
            return False
        return bool(_FOLLOW_UP_PATTERN.search(text))

    @staticmethod
    def _looks_like_light_query(text: str) -> bool:
        if not text or len(text) > 120:
            return False
        return bool(_LIGHT_QUERY_PATTERN.search(text))

    @staticmethod
    def _looks_like_simple_question(text: str) -> bool:
        if not text or len(text) > 100:
            return False
        return bool(_SIMPLE_QUESTION_PATTERN.search(text))

    @staticmethod
    def _looks_like_en_collection(text: str) -> bool:
        if not text:
            return False
        return bool(_EN_COLLECTION_PATTERN.search(text))

    @staticmethod
    def is_not_implemented(workflow_type: str) -> bool:
        return workflow_type in _NOT_IMPL_TYPES
