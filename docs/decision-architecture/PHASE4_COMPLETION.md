# Phase 4 完成清单（中文）

**项目：** Agent 决策架构重构  
**阶段：** Phase 4 — Planner  
**完成日期：** 2026-09-06  
**是否切换生产路径：** **否**（仅 Planner + 金标 + Shadow；`ConversationService` 未接入）

---

## 1. 修改了什么

- 新增 [`decision_planner.py`](../../backend/app/application/services/decision_planner.py)
  - 输入：`DecisionIntent` + `DecisionEntities` + `DecisionContext`
  - 输出：`ExecutionPlan`（`clarify` / `short_answer` / `research` / `deep_fast` / `deep_full` / `follow_up` / `oos`）
  - **禁止隐式默认 Deep**（仅 `task_family=analyze` 或 `discourse=upgrade_prior` 可出 deep_*）
  - 升级完整报告：`deep_full` + step `upgrade_analysis`（Shadow 与现网 Router `follow_up` 兼容）
  - 提供 `shadow_compare_plan_vs_router_workflow`、`assert_no_implicit_deep`
- 新增 Planner 金标 [`planner_goldens.json`](../../backend/tests/fixtures/planner_goldens.json)（含正反例成对）
- 新增单测 [`test_decision_planner_phase4.py`](../../backend/tests/unit/test_decision_planner_phase4.py)

## 2. 没有修改什么

- 生产会话主路径（仍为 Legacy Intent → Router → Executor）
- Router 业务优先级逻辑（未再堆语义正则）
- Deep / Research / Memory / UI / DB
- Phase 0–3 金标期望（Router / Intent / Entity）

## 3. 新增了什么 Contract / 能力

沿用 Phase 1 `ExecutionPlan`。Planner 决策摘要：

| Intent | 条件 | execution_mode |
|--------|------|----------------|
| `oos` | — | `oos` |
| `advise_prior` + `upgrade_prior` | 有 prior/实体 | `deep_full`（或 fast hint） |
| `advise_prior` | 短答 | `follow_up` |
| `ask` listing/definition/dynamics | — | `short_answer` |
| `collect` | 有公司或产品 | `research` |
| `collect` / `analyze` 缺槽 | — | `clarify` |
| `analyze` | 公司+产品+竞品 | `deep_fast` / `deep_full` |
| 其他 | — | `short_answer`（**不** deep） |

## 4. 修改了哪些模块

| 路径 | 说明 |
|------|------|
| `backend/app/application/services/decision_planner.py` | 新增 |
| `backend/tests/fixtures/planner_goldens.json` | 新增 |
| `backend/tests/unit/test_decision_planner_phase4.py` | 新增 |
| `docs/decision-architecture/PHASE4_COMPLETION.md` | 本文件 |

## 5. 测试结果

```text
pytest tests/unit/test_decision_planner_phase4.py \
  tests/unit/test_decision_entity_phase3.py \
  tests/unit/test_decision_intent_phase2.py \
  tests/unit/test_decision_contracts_phase1.py \
  tests/unit/test_router_goldens_pr_v26.py \
  tests/unit/test_router_service_pr_v21.py \
  tests/unit/test_intent_mapper_routing.py \
  tests/unit/test_follow_up_service.py \
  -q
→ 75 passed
```

## 6. Regression 结果

| 门禁 | 结果 |
|------|------|
| Planner critical 金标 | 通过 |
| 禁止隐式 Deep 不变量 | 通过 |
| 正反例成对（追问建议 vs 显式 CA） | 通过 |
| Planner ↔ Router Shadow ≥ 85% | 通过 |
| Phase 0–3 回归 | 通过 |

## 7. 新发现的问题 / Follow-up

1. **升级路径双语义：** Planner 用 `deep_full`，现网 Router 标 `follow_up` 再由 FollowUpService 升级；Shadow 已特判兼容，Phase 5 Thin Router 需统一 Capability 映射。  
2. **analyze 缺竞品即 clarify：** 现网可用 curated 自动补全后开跑；Planner 更严。Entity 已能 curated 填 peers 时，调用方应先跑 Entity 再 Plan（E2E smoke 已覆盖）。若 Entity 未填 comps，会澄清——可在 Phase 5 按产品策略放宽。  
3. **仍无生产 shadow 日志落盘：** 仅单测离线对比。  
4. **multi_step 未实现：** 留给 Phase 6。

## 8. 下一 Phase 建议

进入 **Phase 5 — Thin Router**：

- `ExecutionPlan` → Capability / Executor 映射表  
- `ConversationService` 特性开关：`legacy_router` vs `planner_path`  
- 冻结 Router 语义正则扩展；legacy 仅作回退  
- 切换前保持 Shadow 对比与 critical 100%

**请确认后再批准 Phase 5。**

---

## 范围核对

- [x] 禁止隐式默认 Deep  
- [x] 规则带正例 + 反例金标  
- [x] 未切生产路径  
- [x] 未无关重构 Deep/Research/Memory/UI  
- [x] 完成清单中文交付  
