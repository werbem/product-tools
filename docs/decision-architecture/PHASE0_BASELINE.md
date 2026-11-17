# Phase 0 — Router Decision Baseline Freeze

**Status:** frozen  
**Date:** 2026-09-06  
**Production impact:** none (fixtures + docs + meta tests only)

## Purpose

Capture what the current overloaded `RouterService` does **today**, so later Intent / Entity / Planner phases cannot silently change routing behavior without failing eval gates.

## Baseline snapshot

Source of truth: [`backend/tests/fixtures/router_baseline_snapshot.json`](../../backend/tests/fixtures/router_baseline_snapshot.json)

| Metric | Value |
|--------|-------|
| Fixture | `backend/tests/fixtures/router_goldens.json` (version 2) |
| Cases | 34 |
| Critical cases | 24 |
| Critical accuracy | **100%** (required) |
| Overall accuracy | **100%** (threshold ≥ 95%) |
| Gates OK | yes |

### Counts by expect workflow

| workflow_type | count |
|---------------|------:|
| competitive_analysis | 6 |
| research | 6 |
| information_query | 3 |
| simple_question | 9 |
| follow_up | 6 |
| out_of_scope | 4 |

### Counts by slice

| slice | count |
|-------|------:|
| ca_launch | 6 |
| research | 6 |
| information_query | 3 |
| simple_question | 9 |
| follow_up | 6 |
| out_of_scope | 4 |

### Critical case IDs

`ca_commercial_behavior_report`, `ca_feizhu_meituan_strategy`, `ca_vs_full_report`, `ca_en_commercial_behavior`, `ca_analyze_and_collect_support`, `ca_explicit_with_prior_still_deep`, `res_douyin_collect`, `res_ctrip_membership_materials`, `res_meituan_survey_dynamics`, `mix_collect_ca_report_materials`, `iq_meituan_recent_changes`, `sq_ctrip_membership_how`, `sq_feizhu_what_company`, `sq_longteng_who`, `sq_yuetu_oneliner`, `mix_commercial_behavior_types`, `fu_pricing_with_prior`, `fu_based_on_this_info_ops_advice`, `fu_ops_advice_no_deixis`, `fu_pricing_no_prior`, `fu_continue_full_ca_report`, `oos_weather`, `oos_leave_email`, `oos_what_time`

## Slice map → target contracts (Phase 1+)

| Slice | Target `task_family` (v1) | Target `execution_mode` (v1) |
|-------|---------------------------|------------------------------|
| ca_launch | analyze | deep_fast / deep_full |
| research | collect | research |
| information_query | ask (dynamics) | short_answer |
| simple_question | ask (definition/listing) | short_answer |
| follow_up | advise_prior / continue | follow_up (short or upgrade via Planner) |
| out_of_scope | oos | oos |

## Additive golden fields (Phase 0)

Each case now includes:

- `slice` — one of the required slices above
- `tags[]` — vocabulary includes `ca_launch`, `research`, `information_query`, `simple_question`, `follow_up`, `follow_up_deixis`, `follow_up_advice`, `follow_up_upgrade`, `follow_up_negative`, `listing`, `oos`, `confusable`

**Rule:** Do not change `expect_workflow_type` without `baseline_exception` + written rationale. Prefer dual +/- goldens when changing behavior after Phase 2.

## Failure taxonomy (known product / architecture debt)

These are **classified debts**, not necessarily failing goldens today. They motivate Phase 2–5.

| ID | Class | Symptom | Root cause layer |
|----|-------|---------|------------------|
| T1 | discourse_miss | Ops advice without「基于刚才」opened Deep | Router semantic regex + LegacyBridge default Deep |
| T2 | invalid_entity_inherit | 「它都」from「它都有哪些竞品」stored in Memory and reused | Entity extraction / sanitization |
| T3 | listing_vs_ca_dual | Listing +「分析报告」mis-routed | Intent + Router priority |
| T4 | collection_nested_report | 「收集…竞品分析报告资料」risked CA | Intent mapper collection-primary |
| T5 | clarification_blocks_light | Missing competitors blocked light Q&A | Conversation clarification vs Router probe |
| T6 | router_priority_collision | Fixing follow_up regex changes CA / research | Overloaded Router |

### Known debt flags (snapshot)

- `legacy_bridge_default_deep_without_launch_signal`
- `router_semantic_regex_overload`
- `entity_fill_does_not_imply_deep_launch`

## Anti-regression rule (Principle 5)

Any Intent / Planner rule after Phase 2 **must** land with:

1. One **positive** golden (desired path)
2. One **negative** golden (must not steal the other path)

Example pair already in fixture:

- (+) `fu_ops_advice_no_deixis` → follow_up  
- (−) `ca_explicit_with_prior_still_deep` → competitive_analysis  

## What Phase 0 did / did not change

| Changed | Not changed |
|---------|-------------|
| Golden `slice` / `tags` | `RouterService` routing logic |
| Golden meta tests | `ConversationService` |
| Baseline docs + snapshot JSON | Intent prompts / Memory / Deep / UI |

## How to re-verify gates

```bash
cd backend && PYTHONPATH=. pytest \
  tests/unit/test_router_goldens_pr_v26.py \
  tests/unit/test_router_service_pr_v21.py \
  tests/unit/test_intent_mapper_routing.py \
  tests/unit/test_follow_up_service.py \
  -q
```

## Phase 0 completion checklist

1. **Modified:** golden fixture metadata, golden meta test, baseline docs/snapshot  
2. **Not modified:** production routing / intent / executors  
3. **New contracts:** none yet (Phase 1)  
4. **Modules:** `router_goldens.json`, `test_router_goldens_pr_v26.py`, `docs/decision-architecture/*`  
5. **Tests:** see snapshot `gates_ok`  
6. **Regression:** overall 100%, critical 100% at freeze  
7. **New issues:** taxonomy T1–T6 tracked for later phases  
8. **Next:** Phase 1 Decision contracts + adapters (no production wiring)

## Next phase recommendation

Proceed to Phase 1: add `backend/app/application/dto/decision/*` contracts and legacy adapters; do not wire `ConversationService`.
