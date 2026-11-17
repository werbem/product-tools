# Phase 6 完成清单（中文）

**项目：** Agent 决策架构重构  
**阶段：** Phase 6 — Multi-step Planning  
**完成日期：** 2026-09-06  
**生产默认：** **`DECISION_PLANNER_ROUTING=off`**（与 Phase 5 相同；`on` 时 terminal workflow 驱动现有 Executor）

---

## 1. 修改了什么

- 新增 [`decision_multi_step.py`](../../backend/app/application/services/decision_multi_step.py)  
  - `detect_multi_step_combo`：显式链式组合（非 Router 优先级 hack）  
  - `listing_then_analyze` / `collect_then_advise` / `collect_then_analyze`  
  - 嵌套「收集竞品分析报告相关资料」保持单步，不进 multi_step  
- [`decision_planner.py`](../../backend/app/application/services/decision_planner.py)  
  - OOS 之后、单 family 分支之前生成 `execution_mode=multi_step` + `PlanStep` 链  
  - terminal `workflow_type`：分析类 → `competitive_analysis`；收集+建议 → `research`  
  - `assert_no_implicit_deep` / shadow 兼容 multi_step  
- [`decision_thin_router.py`](../../backend/app/application/services/decision_thin_router.py)  
  - `capability=multi_step`；metadata 写入 `step_ops` / `steps` / `terminal_op`  
  - **仍用 terminal `workflow_type` 兼容现网 Executor**（完整多步 runner 留给后续）  
- [`decision_routing.py`](../../backend/app/application/services/decision_routing.py)  
  - decision_stack meta 暴露 `step_ops` / `multi_step`  
- 金标：`planner_goldens.json` 增加正反例  
- 单测：`test_decision_multi_step_phase6.py`

## 2. 没有修改什么

- 默认 flag=`off` 生产路径  
- ConversationService 仍按 `workflow_type` 分支（未实现逐步执行引擎）  
- Legacy Router 语义正则（继续冻结）  
- Deep / Research 工作流内部、Memory、UI

## 3. 新增了什么能力

| Combo | PlanStep 链 | Terminal workflow |
|-------|-------------|-------------------|
| listing → analyze | `list_competitors` → `deep_analysis` | `competitive_analysis` |
| collect → advise | `intelligence_collection` → `follow_up_short_answer` | `research` |
| collect → analyze | `intelligence_collection` → `deep_analysis` | `competitive_analysis` |

## 4. 修改了哪些模块

| 路径 | 说明 |
|------|------|
| `decision_multi_step.py` | 新增 |
| `decision_planner.py` | multi_step 规划 |
| `decision_thin_router.py` | steps metadata |
| `decision_routing.py` | meta 透传 |
| `planner_goldens.json` | Phase 6 金标 |
| `test_decision_multi_step_phase6.py` | 新增 |
| `PHASE6_COMPLETION.md` | 本文件 |

## 5. 测试结果

```text
pytest …(Phase1–6 + Router/follow_up + dual listing)… -q
→ 98 passed
```

## 6. Regression 结果

| 门禁 | 结果 |
|------|------|
| listing-only → short_answer | 通过 |
| listing+分析报告 → multi_step | 通过 |
| 嵌套「收集…报告相关资料」→ research（非 multi） | 通过 |
| collect+运营建议 → multi_step(research) | 通过 |
| ThinRouter on：terminal CA workflow | 通过 |
| 默认 off 无行为变化 | 通过 |

## 7. 新发现的问题 / Follow-up

1. **尚无逐步 Executor**：`on` 时只跑 terminal workflow（如直接 Deep），不会先执行 `list_competitors` 再 Deep。Phase 7/后续可加 capability switch + step runner。  
2. **collect→analyze 与 Legacy Router 可能 shadow 不一致**：Planner 倾向 CA terminal，Legacy 可能仍 research；`multi_step` 兼容集已包含两者。  
3. **建议先 shadow 观察** `decision_stack.step_ops` 再考虑 `on`。

## 8. 下一 Phase 建议

进入 **Phase 7 — E2E Eval**（全链路评测门禁），再考虑默认开启 Planner 路径或实现真正的 multi-step runner。

---

## 范围核对

- [x] PlanStep 组合表达 listing→analyze、collect→advise/analyze  
- [x] 单步 listing / nested collect 不误伤  
- [x] ThinRouter 暴露 multi_step + terminal workflow  
- [x] 正反例金标 + 单测  
- [x] 完成清单中文交付  
- [x] 默认不切生产（off）  
