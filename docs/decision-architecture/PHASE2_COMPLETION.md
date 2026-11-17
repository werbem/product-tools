# Phase 2 完成清单（中文）

**项目：** Agent 决策架构重构  
**阶段：** Phase 2 — Intent Extraction  
**完成日期：** 2026-09-06  
**是否切换生产路径：** **否**（仅独立抽取器 + 金标 + shadow 对比；会话主路径仍走 Legacy Intent → Router）

---

## 1. 修改了什么

- 新增共享信号模块 [`decision_intent_signals.py`](../../backend/app/application/services/decision_intent_signals.py)  
  - 将原先散落在 Router 中的域外 / 指代追问 / 软建议 / 轻问 / 简单问 / 英文收集 / 升级报告等模式收归 Intent 侧
- 新增规则抽取器 [`decision_intent_extractor.py`](../../backend/app/application/services/decision_intent_extractor.py)  
  - 输出 `DecisionIntent`：`task_family` / `discourse` / `ask_subtype` / `confidence` / `signals`  
  - **无开跑信号时不默认 `analyze`**（禁止在 Intent 层隐式 Deep）
  - 提供 `shadow_compare_intent_vs_router_workflow` 离线对比
- Router 改为 **引用** 共享信号函数（行为保持与 Phase 0 baseline 一致，不新增语义正则）
- 新增 Intent 金标 [`intent_goldens.json`](../../backend/tests/fixtures/intent_goldens.json)（34 条）
- 新增单测 [`test_decision_intent_phase2.py`](../../backend/tests/unit/test_decision_intent_phase2.py)

## 2. 没有修改什么

- `ConversationService` 生产编排（未接入 `DecisionIntentExtractor`）
- Intent LLM Prompt / `IntentUnderstandingService` 主逻辑
- Deep / Research / Memory / UI / 数据库
- Router 的优先级语义与 Phase 0 `expect_workflow_type`（无改金标期望）

## 3. 新增了什么 Contract / 能力

- **能力：** `DecisionIntentExtractor.extract(message, has_prior=...)`  
- **Shadow：** Intent `task_family` ↔ Router `workflow_type` 兼容桶对比  
- **契约：** 继续使用 Phase 1 的 `DecisionIntent`（无改字段集）

### task_family 判定要点

| 条件 | task_family | discourse |
|------|-------------|-----------|
| 域外硬模式 | `oos` | `new` |
| 升级完整报告 +（指代或 prior） | `advise_prior` | `upgrade_prior` |
| 指代追问（基于刚才/这个信息…） | `advise_prior` | `continue_prior` |
| prior + 运营/下一步建议（可无指代词） | `advise_prior` | `continue_prior` |
| 竞品分析信号（非收集主意图） | `analyze` | `new` |
| 收集/调研信号 | `collect` | `new` |
| listing / 定义 / 动态问 | `ask` | `new` 或 `continue_prior` |
| prior 且无开跑信号 | `advise_prior` | `continue_prior` |
| 无信号新开场 | `ask`/`other`（低置信） | `new` |

## 4. 修改了哪些模块

| 路径 | 说明 |
|------|------|
| `backend/app/application/services/decision_intent_signals.py` | 新增 |
| `backend/app/application/services/decision_intent_extractor.py` | 新增 |
| `backend/app/application/services/router_service.py` | 改为引用共享信号 |
| `backend/tests/fixtures/intent_goldens.json` | 新增 |
| `backend/tests/unit/test_decision_intent_phase2.py` | 新增 |
| `docs/decision-architecture/PHASE2_COMPLETION.md` | 本文件 |

## 5. 测试结果

```text
pytest tests/unit/test_decision_intent_phase2.py \
  tests/unit/test_router_goldens_pr_v26.py \
  tests/unit/test_router_service_pr_v21.py \
  tests/unit/test_intent_mapper_routing.py \
  tests/unit/test_follow_up_service.py \
  tests/unit/test_decision_contracts_phase1.py \
  -q
→ 65 passed
```

## 6. Regression 结果

| 门禁 | 结果 |
|------|------|
| Router critical 100% | 通过 |
| Router overall ≥ 95% | 通过（仍为 100%） |
| Intent critical 100% | 通过 |
| Intent overall ≥ 95% | 通过 |
| Shadow 同意率 ≥ 90% | 通过 |
| 正反例成对（运营建议 vs 显式 CA） | 通过 |

## 7. 新发现的问题 / Follow-up

1. **Shadow 桶映射是粗粒度的**：`ask` 同时兼容 `simple_question` 与 `information_query`；Planner 阶段需更细的 `execution_mode`。  
2. **Legacy Intent LLM 仍与规则 Intent 并行**：生产仍可能填满实体后走 Router；Phase 4/5 才用 Planner 消解。  
3. **FollowUpService 升级正则**仍在 follow_up 模块内；与 `UPGRADE_PRIOR_PATTERN` 语义重复，后续可统一引用 signals（记 Follow-up，本阶段未强行改 FollowUpService 以免越界）。  
4. 未做线上 shadow 日志落盘；当前仅单测内离线对比。

## 8. 下一 Phase 建议

进入 **Phase 3 — Entity Extraction**：

- 封装 `intent_entities` + Memory 回填为 `DecisionEntities`（带 `source`）
- **禁止** Entity 直接触发 Workflow
- 继续不切生产；为 Phase 4 Planner 准备输入

**验收后再批准 Phase 3。**

---

## 范围核对（本阶段禁止项）

- [x] 未为修单一 case 新增 Router 全局语义正则  
- [x] 未改 Deep / Research / Memory / UI / DB  
- [x] 未切换 ConversationService 主路径  
- [x] 新增规则带正例 + 反例金标  

## 冻结声明

Phase 2 已完成并可冻结。生产行为与 Phase 0 baseline 对齐；新 Intent 抽取器可独立评测，待批准后进入 Phase 3。
