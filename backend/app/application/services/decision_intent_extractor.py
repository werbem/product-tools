"""Decision Intent extraction — rules first (Phase 2).

Produces ``DecisionIntent`` (task_family / discourse / ask_subtype / confidence).
Does NOT select workflow launch or call executors.
Not wired into ConversationService production path in Phase 2 (shadow only).
"""

from __future__ import annotations

from app.application.dto.decision.intent_contract import (
    AskSubtype,
    DecisionIntent,
    Discourse,
    TaskFamily,
)
from app.application.services.decision_intent_signals import (
    collect_debug_signals,
    extract_focus_clause,
    looks_like_advice_follow_up,
    looks_like_en_collection,
    looks_like_follow_up_deixis,
    looks_like_light_query,
    looks_like_out_of_scope,
    looks_like_simple_question,
    looks_like_upgrade_prior,
)
from app.application.services.intent_entities import looks_like_competitor_listing_query
from app.application.services.intent_mapper import (
    collection_primary_over_nested_analysis,
    detect_analysis_intent,
    detect_collection_intent,
)


class DecisionIntentExtractor:
    """Rule-based Intent extractor aligned with Phase 0 slice semantics."""

    def extract(
        self,
        message: str,
        *,
        has_prior: bool = False,
        objective_hint: str | None = None,
    ) -> DecisionIntent:
        text = (message or "").strip()
        if not text:
            raise ValueError("message must not be empty")

        signals = collect_debug_signals(text)
        focus = extract_focus_clause(text)
        has_analysis = detect_analysis_intent(text)
        has_collection = detect_collection_intent(text) or looks_like_en_collection(text)

        # 1) OOS
        if looks_like_out_of_scope(text):
            return self._result(
                "oos",
                "new",
                None,
                text,
                signals,
                confidence=0.95,
                focus=focus,
                objective=objective_hint,
            )

        # 2) Upgrade prior (完整报告 etc.) — discourse wins over bare analyze
        if looks_like_upgrade_prior(text) and (
            looks_like_follow_up_deixis(text) or has_prior
        ):
            return self._result(
                "advise_prior",
                "upgrade_prior",
                "advice" if looks_like_advice_follow_up(text) else None,
                text,
                signals,
                confidence=0.88,
                focus=focus,
                objective=objective_hint,
            )

        # 3) Explicit deixis follow-up
        if looks_like_follow_up_deixis(text):
            subtype: AskSubtype | None = (
                "advice" if looks_like_advice_follow_up(text) else "other"
            )
            # Deixis + strong new CA without upgrade → still continue_prior advise
            # unless user clearly launches new analysis without prior framing.
            family: TaskFamily = "advise_prior"
            if has_analysis and not has_prior and not looks_like_upgrade_prior(text):
                # e.g. unlikely; keep advise_prior when deixis present
                family = "advise_prior"
            return self._result(
                family,
                "continue_prior",
                subtype,
                text,
                signals,
                confidence=0.85 if has_prior else 0.55,
                focus=focus,
                objective=objective_hint,
            )

        # 4) Soft advice with prior (no deixis required)
        if (
            has_prior
            and not has_analysis
            and not has_collection
            and looks_like_advice_follow_up(text)
        ):
            return self._result(
                "advise_prior",
                "continue_prior",
                "advice",
                text,
                signals,
                confidence=0.8,
                focus=focus,
                objective=objective_hint,
            )

        # 5) Analyze vs collect
        if has_analysis and has_collection:
            if collection_primary_over_nested_analysis(text):
                return self._result(
                    "collect",
                    "new",
                    None,
                    text,
                    signals,
                    confidence=0.86,
                    focus=focus,
                    objective=objective_hint or "intelligence_collection",
                )
            return self._result(
                "analyze",
                "new",
                None,
                text,
                signals,
                confidence=0.9,
                focus=focus,
                objective=objective_hint,
            )
        if has_analysis:
            return self._result(
                "analyze",
                "new",
                None,
                text,
                signals,
                confidence=0.9,
                focus=focus,
                objective=objective_hint,
            )
        if has_collection:
            return self._result(
                "collect",
                "new",
                None,
                text,
                signals,
                confidence=0.88,
                focus=focus,
                objective=objective_hint or "intelligence_collection",
            )

        # 6) Ask forms
        if looks_like_competitor_listing_query(text):
            return self._result(
                "ask",
                "continue_prior" if has_prior else "new",
                "listing",
                text,
                signals,
                confidence=0.88,
                focus=focus,
                objective=objective_hint,
            )
        if looks_like_light_query(text):
            return self._result(
                "ask",
                "new",
                "dynamics",
                text,
                signals,
                confidence=0.78,
                focus=focus,
                objective=objective_hint,
            )
        if looks_like_simple_question(text):
            return self._result(
                "ask",
                "continue_prior" if has_prior else "new",
                "definition",
                text,
                signals,
                confidence=0.75,
                focus=focus,
                objective=objective_hint,
            )

        # 7) Prior + no launch signal → advise_prior (no implicit analyze)
        if has_prior and not has_analysis and not has_collection:
            subtype = "advice" if looks_like_advice_follow_up(text) else "other"
            return self._result(
                "advise_prior",
                "continue_prior",
                subtype,
                text,
                signals,
                confidence=0.72,
                focus=focus,
                objective=objective_hint,
            )

        # 8) Ambiguous new turn — ask/other, NOT analyze (ban implicit Deep at Intent)
        return self._result(
            "ask",
            "new",
            "other",
            text,
            signals,
            confidence=0.4,
            focus=focus,
            objective=objective_hint,
        )

    @staticmethod
    def _result(
        task_family: TaskFamily,
        discourse: Discourse,
        ask_subtype: AskSubtype | None,
        raw_message: str,
        signals: list[str],
        *,
        confidence: float,
        focus: str | None,
        objective: str | None,
    ) -> DecisionIntent:
        return DecisionIntent(
            task_family=task_family,
            discourse=discourse,
            ask_subtype=ask_subtype,
            objective=objective,
            focus=focus,
            confidence=confidence,
            raw_message=raw_message,
            signals=signals,
        )


def shadow_compare_intent_vs_router_workflow(
    *,
    decision_intent: DecisionIntent,
    router_workflow_type: str,
) -> dict[str, object]:
    """Offline shadow helper: map Intent family → expected workflow family bucket."""
    family_to_workflows: dict[str, set[str]] = {
        "analyze": {"competitive_analysis"},
        "collect": {"research"},
        "ask": {"information_query", "simple_question"},
        "advise_prior": {"follow_up"},
        "oos": {"out_of_scope"},
    }
    expected = family_to_workflows.get(decision_intent.task_family, set())
    agree = router_workflow_type in expected
    return {
        "agree": agree,
        "task_family": decision_intent.task_family,
        "discourse": decision_intent.discourse,
        "ask_subtype": decision_intent.ask_subtype,
        "intent_confidence": decision_intent.confidence,
        "router_workflow_type": router_workflow_type,
        "compatible_workflows": sorted(expected),
        "signals": list(decision_intent.signals),
    }
