# Phase 5 完成清单（中文）

**项目：** Agent 决策架构重构  
**阶段：** Phase 5 — Thin Router  
**完成日期：** 2026-09-06  
**生产默认：** **`DECISION_PLANNER_ROUTING=off`**（仍走 Legacy Router；可 shadow / on 切换）

---

## 1. 修改了什么

- 新增 [`decision_thin_router.py`](../../backend/app/application/services/decision_thin_router.py)  
  - `ExecutionPlan` → `CapabilityDecision`（capability + 兼容现网的 `RoutingDecision`）  
  - **无语义正则**，只做映射表  
- 新增 [`decision_routing.py`](../../backend/app/application/services/decision_routing.py)  
  - `run_decision_stack`：Intent → Entity → Planner → ThinRouter  
  - `apply_decision_routing`：`off` / `shadow` / `on`  
- [`conversation_service.py`](../../backend/app/application/services/conversation_service.py)  
  - 在 Legacy 路由之后接入 decision stack（默认 off 无行为变化）  
  - `on` 且 Planner 要求澄清时，走澄清回复  
  - metadata 写入 `decision_stack`（shadow/on）  
- [`settings.py`](../../backend/app/config/settings.py) + [`.env.example`](../../backend/.env.example)  
  - `decision_planner_routing` / `DECISION_PLANNER_ROUTING`  
- Router 文档标注：禁止再加语义正则，仅作 fallback  

## 2. 没有修改什么

- 默认生产行为（flag=off 时与 Phase 0 baseline 一致）  
- Deep / Research 工作流内部、Memory 存储、UI、DB  
- 未默认开启 `on`（避免未充分 Shadow 就切流量）

## 3. 新增了什么 Contract / 能力

| Capability | 来自 execution_mode |
|------------|---------------------|
| `reject_oos` | oos |
| `clarify` | clarify |
| `short_answer` | short_answer |
| `follow_up` | follow_up |
| `research` | research |
| `deep_analysis` | deep_fast / deep_full |
| `multi_step` | multi_step（预留） |

### 开关

| 值 | 行为 |
|----|------|
| `off`（默认） | 仅 Legacy Router |
| `shadow` | 仍执行 Legacy；metadata 附带 Planner/Thin 对比 |
| `on` | 使用 Thin Router 的 `RoutingDecision` 驱动现有 Executor |

## 4. 修改了哪些模块

| 路径 | 说明 |
|------|------|
| `decision_thin_router.py` | 新增 |
| `decision_routing.py` | 新增 |
| `conversation_service.py` | 接入开关 |
| `settings.py` / `.env.example` | 配置项 |
| `router_service.py` | 文档冻结声明 |
| `test_decision_thin_router_phase5.py` | 新增 |
| `PHASE5_COMPLETION.md` | 本文件 |

## 5. 测试结果

```text
pytest …(Phase1–5 + Router/follow_up)… -q
→ 84 passed
```

## 6. Regression 结果

| 门禁 | 结果 |
|------|------|
| 默认 off 不改变 Legacy 行为 | 通过（既有金标全绿） |
| ThinRouter 映射单测 | 通过 |
| on：运营追问 → follow_up（纠偏 Legacy Deep） | 通过 |
| on：显式 CA → deep_analysis | 通过 |
| shadow：保留 Legacy + 写 meta | 通过 |

## 7. 新发现的问题 / Follow-up

1. **Executor 仍按 `workflow_type` 分支**：Capability 尚未直接驱动；Phase 6/7 可改为 capability switch。  
2. **`on` 与 Legacy 澄清路径并存**：Planner clarify 与 Intent LLM `needs_clarification` 可能双轨，需产品确认优先级。  
3. **建议先 shadow 观察**：对比 `decision_stack.shadow_plan.agree` 再开 `on`。  
4. **multi_step Capability 仅占位**：Phase 6 再实现组合任务。

## 8. 下一 Phase 建议

进入 **Phase 6 — Multi-step Planning**（listing→research→compare→report 等 PlanStep 链），或先 **Phase 7 E2E Eval** 若希望先把评测门禁做厚。

本地试用 Shadow：

```bash
export DECISION_PLANNER_ROUTING=shadow
# 重启 uvicorn 后看消息 metadata.decision_stack
```

启用 Planner 路径（谨慎）：

```bash
export DECISION_PLANNER_ROUTING=on
```

---

## 范围核对

- [x] Thin Router 无语义正则  
- [x] 默认不切生产（off）  
- [x] Legacy Router 保留作 fallback  
- [x] 正反例（追问 vs 显式 CA）在 on 模式覆盖  
- [x] 完成清单中文交付  
