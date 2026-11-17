# Phase 0 + Phase 1 Completion Checklist

**Program:** Agent Decision Architecture Refactor  
**Completed:** 2026-09-06  
**Production cutover:** **No** — legacy path unchanged

---

## Phase 0

### 1. What changed
- Added `slice` + `tags[]` to all Router goldens (`router_goldens.json` v2)
- Golden meta test requires slices/tags and non-empty required slices
- Wrote `PHASE0_BASELINE.md` + `router_baseline_snapshot.json`
- Failure taxonomy T1–T6 documented

### 2. What did not change
- `RouterService` routing behavior
- `ConversationService` / Intent prompts / Memory / Deep / UI

### 3. New contracts
- None (baseline only)

### 4. Modules touched
- `backend/tests/fixtures/router_goldens.json`
- `backend/tests/fixtures/router_baseline_snapshot.json`
- `backend/tests/unit/test_router_goldens_pr_v26.py`
- `docs/decision-architecture/PHASE0_BASELINE.md`
- `docs/decision-architecture/PLAN_ZH.md` (pre-existing confirm doc)

### 5–6. Tests / Regression
- See snapshot: 34/34 overall, 24/24 critical, `gates_ok: true`

### 7. New issues
- Known debt: default Deep without launch signal; Router regex overload (tracked for Phase 4–5)

### 8. Next
- Phase 1 contracts (done below)

---

## Phase 1

### 1. What changed
- Added `backend/app/application/dto/decision/` contracts + adapters
- Unit tests `test_decision_contracts_phase1.py`
- Wrote `PHASE1_CONTRACTS.md`

### 2. What did not change
- No imports of decision package from `ConversationService` / `RouterService`
- No production behavior change

### 3. New contracts
- `DecisionIntent`, `DecisionEntities`, `DecisionContext`, `ExecutionPlan` (+ related enums/slots)

### 4. Modules touched
- `backend/app/application/dto/decision/*`
- `backend/tests/unit/test_decision_contracts_phase1.py`
- `docs/decision-architecture/PHASE1_CONTRACTS.md`

### 5–6. Tests / Regression
- Decision contract tests + Router golden suite (must remain green)

### 7. New issues / Follow-up Tasks
- Phase 2: `DecisionIntentExtractor` (rules first; move discourse signals out of Router)
- Phase 3: Entity provenance sources
- Phase 4: Planner + ban default Deep; shadow mode
- Phase 5: Thin Router + feature flag cutover
- Test hygiene: `test_follow_up_service` conv_env now stubs `_resolve_long_task_busy` so host uvicorn busy tasks cannot flake unit tests (fixture-only; no prod change)

### 8. Next phase recommendation
**Freeze here.** Start Phase 2 only after explicit approval. Do not add Router semantic regex for architecture gaps.

---

## Freeze gate before Phase 2

- [x] Phase 0 gates green  
- [x] Phase 1 contracts + adapters tested  
- [x] Production path untouched  
- [ ] Product/eng explicit go-ahead for Phase 2 Intent extractor  
