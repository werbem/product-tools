# Phase 1 — Decision Architecture Contracts

**Status:** contracts frozen (v1)  
**Date:** 2026-09-06  
**Production impact:** none — adapters are **not** wired into `ConversationService`

## Purpose

Define typed contracts for Intent / Entity / Context / Plan so Phase 2+ implement against schemas instead of Router regex.

## Module layout

`backend/app/application/dto/decision/`

| Module | Types |
|--------|-------|
| `intent_contract.py` | `DecisionIntent`, `TaskFamily`, `Discourse`, `AskSubtype` |
| `entity_contract.py` | `DecisionEntities`, `EntitySlot`, `EntitySource` |
| `context_contract.py` | `DecisionContext` |
| `plan_contract.py` | `ExecutionPlan`, `PlanStep`, `ExecutionMode` |
| `adapters.py` | Legacy ↔ new mapping |
| `__init__.py` | public exports |

Legacy types remain authoritative in production:

- `IntentUnderstandingResult` — `backend/app/application/dto/intent_dto.py`
- `RoutingDecision` — `backend/app/application/dto/routing_dto.py`

## Contract field summary

### DecisionIntent

| Field | Values |
|-------|--------|
| task_family | `analyze \| collect \| ask \| advise_prior \| oos` |
| discourse | `new \| continue_prior \| upgrade_prior` |
| ask_subtype | `listing \| definition \| dynamics \| advice \| other \| null` |
| objective / focus | optional strings |
| confidence | 0–1 |
| raw_message | required non-empty |
| signals | debug list (not for prod branching in Phase 1) |

### DecisionEntities

| Field | Notes |
|-------|-------|
| company / product / competitors / time_range | each is `EntitySlot{value, source, confidence}` |
| source | `message \| prior \| memory \| curated \| inferred \| unknown` |
| missing_slots | subset of slot names |

**Principle:** filled slots ≠ must launch Deep.

### DecisionContext

Prior artifact flags, prior task/report ids, flat memory company/competitors/product, conversation/project ids.

Must not silently override explicit current-turn Intent (Planner rule later).

### ExecutionPlan

| Field | Notes |
|-------|-------|
| clarification_required / clarification_question | clarify gate |
| execution_mode | `clarify \| short_answer \| research \| deep_fast \| deep_full \| follow_up \| multi_step \| oos` |
| workflow_type | legacy-compatible label |
| steps | `PlanStep[]` |
| planner_confidence / reason | audit |

**Contract note:** no implicit `deep_*` without analyze / upgrade_prior (enforced in Planner Phase 4).

## Slice → contract mapping (from Phase 0)

| Phase 0 slice | task_family | execution_mode (typical) | workflow_type |
|---------------|-------------|--------------------------|---------------|
| ca_launch | analyze | deep_fast / deep_full | competitive_analysis |
| research | collect | research | research |
| information_query | ask + dynamics | short_answer | information_query |
| simple_question | ask + definition/listing | short_answer | simple_question |
| follow_up | advise_prior / ask | follow_up | follow_up |
| out_of_scope | oos | oos | out_of_scope |

## Adapter mapping tables

### `legacy_intent_to_decision_entities`

| Legacy | DecisionEntities |
|--------|------------------|
| `company` | `company.value` (source=`unknown`) |
| `product` | `product.value` |
| `competitors` | `competitors.value` (list) |
| `missing_fields` ∩ {company,product,competitors} | `missing_slots` |
| `confidence` | copied onto non-empty slots |

### `routing_context_to_decision_context`

| Input | DecisionContext |
|-------|-----------------|
| `has_prior_analysis` | `has_prior_artifact` |
| `conversation_id` / `project_id` | same |
| optional memory_* kwargs | flat memory fields |

### `execution_plan_to_routing_decision`

| execution_mode | workflow_type (if unset/alias) | legacy_workflow_kind |
|----------------|--------------------------------|----------------------|
| deep_fast / deep_full | competitive_analysis | deep_analysis |
| research | research | intelligence_collection |
| follow_up | follow_up | null |
| short_answer | simple_question* | null |
| oos | out_of_scope | null |
| clarify | simple_question* (pre-route today) | null |

\* Prefer explicit `plan.workflow_type` when set (e.g. `information_query`).

## Tests

`backend/tests/unit/test_decision_contracts_phase1.py`

## What Phase 1 did / did not change

| Changed | Not changed |
|---------|-------------|
| New `dto/decision/*` | `RouterService` behavior |
| Adapters + unit tests | `ConversationService` wiring |
| This doc | Intent LLM prompts / Memory / Deep / UI |

## Phase 1 completion checklist

1. **Modified:** new decision DTO package + tests + docs  
2. **Not modified:** production call sites  
3. **New contracts:** DecisionIntent / DecisionEntities / DecisionContext / ExecutionPlan  
4. **Modules:** `app/application/dto/decision/*`, `tests/unit/test_decision_contracts_phase1.py`  
5. **Tests:** contract + adapter suite  
6. **Regression:** Phase 0 router goldens still required green  
7. **New issues / Follow-ups:** wire shadow logger (Phase 4); Intent extractor (Phase 2)  
8. **Next:** Phase 2 `DecisionIntentExtractor` (rules first), still no production cutover  

## Freeze before Phase 2

Do not start Intent extractor until:

- Phase 0 gates remain green  
- Phase 1 unit tests green  
- Product/eng accept contract v1 field set
