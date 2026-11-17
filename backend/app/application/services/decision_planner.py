"""Decision Planner — Intent + Entities + Context → ExecutionPlan (Phase 4+6).

Rules only. Production use gated by ``DECISION_PLANNER_ROUTING`` (Phase 5).
Bans implicit deep_fast/deep_full unless analyze / upgrade_prior / multi_step with analyze.
Phase 6: multi_step PlanStep chains for listing→analyze, collect→advise, etc.
"""

from __future__ import annotations

from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import DecisionEntities
from app.application.dto.decision.intent_contract import DecisionIntent
from app.application.dto.decision.plan_contract import (
    ExecutionMode,
    ExecutionPlan,
    PlanStep,
    PlanWorkflowType,
)
from app.application.services.decision_intent_signals import looks_like_upgrade_prior
from app.application.services.decision_multi_step import detect_multi_step_combo


def _prefer_full_report(intent: DecisionIntent) -> bool:
    if intent.discourse == "upgrade_prior":
        return True
    return looks_like_upgrade_prior(intent.raw_message)


class DecisionPlanner:
    """Core execution decision layer for the decision architecture."""

    def plan(
        self,
        intent: DecisionIntent,
        entities: DecisionEntities,
        context: DecisionContext | None = None,
        *,
        analysis_mode_hint: str | None = None,
    ) -> ExecutionPlan:
        ctx = context or DecisionContext()
        company = entities.company_name()
        product = entities.product_name()
        comps = entities.competitor_names()
        conf = float(intent.confidence or 0.5)

        # 1) Out of scope
        if intent.task_family == "oos":
            return self._plan(
                mode="oos",
                workflow="out_of_scope",
                reason="intent_oos",
                confidence=max(conf, 0.9),
                steps=[PlanStep(op="reject_oos")],
            )

        # 1b) Multi-step combos (Phase 6) — before single-family branches
        combo = detect_multi_step_combo(intent.raw_message)
        if combo:
            multi = self._plan_multi_step(
                combo=combo,
                intent=intent,
                company=company,
                product=product,
                comps=comps,
                entities=entities,
                conf=conf,
                analysis_mode_hint=analysis_mode_hint,
            )
            if multi is not None:
                return multi

        # 2) Advise / follow prior
        if intent.task_family == "advise_prior":
            if intent.discourse == "upgrade_prior":
                return self._plan_upgrade(
                    intent, company, product, comps, ctx, conf, analysis_mode_hint,
                )
            if not ctx.has_prior_artifact and not (
                company or product or comps
            ):
                return self._plan(
                    mode="follow_up",
                    workflow="follow_up",
                    reason="follow_up_no_prior",
                    confidence=min(conf, 0.55),
                    steps=[PlanStep(op="follow_up_no_prior")],
                )
            return self._plan(
                mode="follow_up",
                workflow="follow_up",
                reason="follow_up_short_answer",
                confidence=max(conf, 0.72),
                steps=[
                    PlanStep(
                        op="follow_up_short_answer",
                        args={
                            "company": company,
                            "product": product,
                            "ask_subtype": intent.ask_subtype,
                        },
                    ),
                ],
            )

        # 3) Ask forms → short answer (never deep)
        if intent.task_family == "ask":
            return self._plan_ask(intent, company, product, comps, conf)

        # 4) Collect → research (clarify if no company/product)
        if intent.task_family == "collect":
            if not company and not product:
                return self._clarify(
                    "请告诉我要收集哪家公司或哪个产品的信息？",
                    reason="collect_missing_entity",
                    confidence=conf,
                )
            return self._plan(
                mode="research",
                workflow="research",
                reason="collect_research",
                confidence=max(conf, 0.8),
                steps=[
                    PlanStep(
                        op="intelligence_collection",
                        args={
                            "company": company,
                            "product": product,
                            "time_range": entities.time_range.value,
                            "focus": intent.focus,
                        },
                    ),
                ],
            )

        # 5) Analyze → deep_* only here (or via upgrade / multi_step above)
        if intent.task_family == "analyze":
            return self._plan_analyze(
                intent, company, product, comps, conf, analysis_mode_hint,
            )

        # 6) Unknown family — short answer / clarify, NEVER default deep
        return self._plan(
            mode="short_answer",
            workflow="simple_question",
            reason="unknown_task_family_no_default_deep",
            confidence=min(conf, 0.4),
            steps=[PlanStep(op="short_answer", args={"fallback": True})],
        )

    def _plan_multi_step(
        self,
        *,
        combo: str,
        intent: DecisionIntent,
        company: str | None,
        product: str | None,
        comps: list[str],
        entities: DecisionEntities,
        conf: float,
        analysis_mode_hint: str | None,
    ) -> ExecutionPlan | None:
        prefer_full = _prefer_full_report(intent) or analysis_mode_hint == "full"
        if analysis_mode_hint == "fast":
            prefer_full = False
        analysis_mode = "full" if prefer_full else "fast"

        if combo == "listing_then_analyze":
            if not company:
                return self._clarify(
                    "请告诉我要查询并分析哪家公司的竞品？",
                    reason="multi_step_listing_analyze_missing_company",
                    confidence=conf,
                )
            if not product:
                return self._clarify(
                    "请告诉我要分析的具体产品或市场是什么？",
                    reason="multi_step_listing_analyze_missing_product",
                    confidence=conf,
                )
            # Competitors may be filled by Entity curated; if empty, listing step
            # is required before deep — still emit chain (deep args may clarify later).
            steps = [
                PlanStep(
                    op="list_competitors",
                    args={
                        "company": company,
                        "product": product,
                        "competitors": comps,
                    },
                ),
                PlanStep(
                    op="deep_analysis",
                    args={
                        "company": company,
                        "product": product,
                        "competitors": comps,
                        "analysis_mode": analysis_mode,
                        "focus": intent.focus,
                    },
                    optional=False,
                ),
            ]
            # Terminal workflow for ThinRouter → existing Deep executor
            return self._plan(
                mode="multi_step",
                workflow="competitive_analysis",
                reason="multi_step_listing_then_analyze",
                confidence=max(conf, 0.86),
                steps=steps,
            )

        if combo == "collect_then_advise":
            if not company and not product:
                return self._clarify(
                    "请告诉我要收集哪家公司或哪个产品的信息？",
                    reason="multi_step_collect_advise_missing_entity",
                    confidence=conf,
                )
            steps = [
                PlanStep(
                    op="intelligence_collection",
                    args={
                        "company": company,
                        "product": product,
                        "time_range": entities.time_range.value,
                        "focus": intent.focus,
                    },
                ),
                PlanStep(
                    op="follow_up_short_answer",
                    args={
                        "company": company,
                        "product": product,
                        "ask_subtype": "advice",
                        "from_collection": True,
                    },
                ),
            ]
            return self._plan(
                mode="multi_step",
                workflow="research",
                reason="multi_step_collect_then_advise",
                confidence=max(conf, 0.82),
                steps=steps,
            )

        if combo == "collect_then_analyze":
            if not company:
                return self._clarify(
                    "请告诉我要收集并分析哪家公司？",
                    reason="multi_step_collect_analyze_missing_company",
                    confidence=conf,
                )
            if not product:
                return self._clarify(
                    "请告诉我要分析的具体产品或市场是什么？",
                    reason="multi_step_collect_analyze_missing_product",
                    confidence=conf,
                )
            steps = [
                PlanStep(
                    op="intelligence_collection",
                    args={
                        "company": company,
                        "product": product,
                        "time_range": entities.time_range.value,
                        "focus": intent.focus,
                    },
                ),
                PlanStep(
                    op="deep_analysis",
                    args={
                        "company": company,
                        "product": product,
                        "competitors": comps,
                        "analysis_mode": analysis_mode,
                        "focus": intent.focus,
                    },
                ),
            ]
            return self._plan(
                mode="multi_step",
                workflow="competitive_analysis",
                reason="multi_step_collect_then_analyze",
                confidence=max(conf, 0.84),
                steps=steps,
            )

        return None

    def _plan_upgrade(
        self,
        intent: DecisionIntent,
        company: str | None,
        product: str | None,
        comps: list[str],
        ctx: DecisionContext,
        conf: float,
        analysis_mode_hint: str | None,
    ) -> ExecutionPlan:
        if not ctx.has_prior_artifact and not (company and product):
            return self._plan(
                mode="follow_up",
                workflow="follow_up",
                reason="upgrade_no_prior",
                confidence=0.5,
                steps=[PlanStep(op="follow_up_no_prior")],
            )
        if not company or not product:
            return self._clarify(
                "升级完整报告前，请确认分析公司与产品名称。",
                reason="upgrade_missing_entities",
                confidence=conf,
            )
        prefer_full = True
        if analysis_mode_hint == "fast":
            prefer_full = False
        mode: ExecutionMode = "deep_full" if prefer_full else "deep_fast"
        return self._plan(
            mode=mode,
            workflow="competitive_analysis",
            reason="follow_up_upgrade_analysis",
            confidence=max(conf, 0.85),
            steps=[
                PlanStep(
                    op="upgrade_analysis",
                    args={
                        "company": company,
                        "product": product,
                        "competitors": comps,
                        "analysis_mode": "full" if prefer_full else "fast",
                    },
                ),
            ],
        )

    def _plan_ask(
        self,
        intent: DecisionIntent,
        company: str | None,
        product: str | None,
        comps: list[str],
        conf: float,
    ) -> ExecutionPlan:
        subtype = intent.ask_subtype or "other"
        if subtype == "dynamics":
            workflow: PlanWorkflowType = "information_query"
            reason = "ask_dynamics_short_answer"
        elif subtype == "listing":
            workflow = "simple_question"
            reason = "ask_listing_short_answer"
            if not company:
                return self._clarify(
                    "请告诉我要查询哪家公司的竞品？",
                    reason="listing_missing_company",
                    confidence=conf,
                )
        elif subtype == "definition":
            workflow = "simple_question"
            reason = "ask_definition_short_answer"
        else:
            workflow = "simple_question"
            reason = "ask_other_short_answer"

        return self._plan(
            mode="short_answer",
            workflow=workflow,
            reason=reason,
            confidence=max(conf, 0.7),
            steps=[
                PlanStep(
                    op="short_answer",
                    args={
                        "ask_subtype": subtype,
                        "company": company,
                        "product": product,
                        "competitors": comps,
                    },
                ),
            ],
        )

    def _plan_analyze(
        self,
        intent: DecisionIntent,
        company: str | None,
        product: str | None,
        comps: list[str],
        conf: float,
        analysis_mode_hint: str | None,
    ) -> ExecutionPlan:
        if not company:
            return self._clarify(
                "请告诉我您要分析哪家公司（分析公司）？",
                reason="analyze_missing_company",
                confidence=conf,
            )
        if not product:
            return self._clarify(
                "请告诉我要分析的具体产品或市场是什么？",
                reason="analyze_missing_product",
                confidence=conf,
            )
        if not comps:
            return self._clarify(
                "请告诉我主要对比哪些竞品？",
                reason="analyze_missing_competitors",
                confidence=conf,
            )
        prefer_full = _prefer_full_report(intent) or analysis_mode_hint == "full"
        if analysis_mode_hint == "fast":
            prefer_full = False
        mode: ExecutionMode = "deep_full" if prefer_full else "deep_fast"
        return self._plan(
            mode=mode,
            workflow="competitive_analysis",
            reason="analyze_deep_launch",
            confidence=max(conf, 0.85),
            steps=[
                PlanStep(
                    op="deep_analysis",
                    args={
                        "company": company,
                        "product": product,
                        "competitors": comps,
                        "analysis_mode": "full" if prefer_full else "fast",
                        "focus": intent.focus,
                    },
                ),
            ],
        )

    @staticmethod
    def _clarify(question: str, *, reason: str, confidence: float) -> ExecutionPlan:
        return ExecutionPlan(
            clarification_required=True,
            clarification_question=question,
            execution_mode="clarify",
            workflow_type="simple_question",
            steps=[PlanStep(op="clarify", args={"question": question})],
            planner_confidence=confidence,
            reason=reason,
        )

    @staticmethod
    def _plan(
        *,
        mode: ExecutionMode,
        workflow: PlanWorkflowType,
        reason: str,
        confidence: float,
        steps: list[PlanStep],
        clarification_required: bool = False,
        clarification_question: str | None = None,
    ) -> ExecutionPlan:
        # Hard ban: deep only via analyze path / upgrade (caller must set mode)
        if mode in ("deep_fast", "deep_full") and reason not in {
            "analyze_deep_launch",
            "follow_up_upgrade_analysis",
        }:
            raise AssertionError(f"implicit deep forbidden: reason={reason}")
        return ExecutionPlan(
            clarification_required=clarification_required,
            clarification_question=clarification_question,
            execution_mode=mode,
            workflow_type=workflow,
            steps=steps,
            planner_confidence=confidence,
            reason=reason,
        )


def shadow_compare_plan_vs_router_workflow(
    *,
    plan: ExecutionPlan,
    router_workflow_type: str,
) -> dict[str, object]:
    """Offline shadow: map plan execution_mode/workflow to Router workflow buckets."""
    # Upgrade currently routes as follow_up in production Router; treat as agree.
    if plan.reason == "follow_up_upgrade_analysis" and router_workflow_type == "follow_up":
        agree = True
        compatible = ["follow_up", "competitive_analysis"]
    elif plan.execution_mode == "clarify":
        # Clarification is pre-route in prod; accept several light types
        compatible = [
            "simple_question",
            "follow_up",
            "information_query",
            "competitive_analysis",
            "research",
        ]
        agree = router_workflow_type in compatible
    else:
        mode_map: dict[str, set[str]] = {
            "oos": {"out_of_scope"},
            "research": {"research"},
            "deep_fast": {"competitive_analysis"},
            "deep_full": {"competitive_analysis"},
            "follow_up": {"follow_up"},
            "short_answer": {"simple_question", "information_query"},
            "multi_step": {"competitive_analysis", "research", "follow_up"},
            "clarify": {"simple_question", "follow_up"},
        }
        compatible_set = mode_map.get(plan.execution_mode, set())
        # Also allow exact workflow_type match
        compatible_set = set(compatible_set)
        compatible_set.add(plan.workflow_type)
        compatible = sorted(compatible_set)
        agree = router_workflow_type in compatible_set

    return {
        "agree": agree,
        "execution_mode": plan.execution_mode,
        "workflow_type": plan.workflow_type,
        "reason": plan.reason,
        "planner_confidence": plan.planner_confidence,
        "router_workflow_type": router_workflow_type,
        "compatible_workflows": compatible,
        "clarification_required": plan.clarification_required,
    }


def assert_no_implicit_deep(plan: ExecutionPlan, intent: DecisionIntent) -> None:
    """Test helper / invariant: deep requires analyze, upgrade_prior, or multi_step*analyze."""
    if plan.execution_mode == "multi_step":
        has_deep = any(
            s.op in ("deep_analysis", "upgrade_analysis") for s in plan.steps
        )
        if has_deep and "analyze" not in (plan.reason or ""):
            raise AssertionError(
                f"multi_step deep without analyze reason: {plan.reason}"
            )
        return
    if plan.execution_mode not in ("deep_fast", "deep_full"):
        return
    ok = intent.task_family == "analyze" or intent.discourse == "upgrade_prior"
    if not ok:
        raise AssertionError(
            f"implicit deep: mode={plan.execution_mode} "
            f"family={intent.task_family} discourse={intent.discourse}"
        )
