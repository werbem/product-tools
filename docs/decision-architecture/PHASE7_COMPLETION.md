# Phase 7 完成清单（中文）

**项目：** Agent 决策架构重构  
**阶段：** Phase 7 — E2E Eval  
**完成日期：** 2026-09-06  
**生产默认：** **仍为 `DECISION_PLANNER_ROUTING=off`**（本阶段只锁门禁，不默认切 `on`）

---

## 1. 修改了什么

- 新增 [`decision_e2e_eval.py`](../../backend/app/application/services/decision_e2e_eval.py)  
  - `evaluate_e2e_case` / `evaluate_e2e_suite`：离线跑 **Intent → Entity → Planner → ThinRouter**  
- 新增金标 [`e2e_decision_goldens.json`](../../backend/tests/fixtures/e2e_decision_goldens.json)（20 条，全 critical）  
- 新增基线快照 [`e2e_decision_baseline_snapshot.json`](../../backend/tests/fixtures/e2e_decision_baseline_snapshot.json)  
- 新增门禁单测 [`test_decision_e2e_phase7.py`](../../backend/tests/unit/test_decision_e2e_phase7.py)  
  - critical **100%**、overall ≥ **95%**  
  - 必覆盖切片、正反例 pair、forbid_deep  

## 2. 没有修改什么

- 未把生产默认改为 `on`  
- 未改 ConversationService / Legacy Router 行为  
- 未实现 multi-step 逐步 Executor  
- 未改 Deep / Research / Memory / UI / DB

## 3. 新增了什么评测能力

| 切片 | 覆盖 |
|------|------|
| `ca_launch` | 新开分析；有 prior 仍显式 CA |
| `research` | 收集；嵌套「报告相关资料」 |
| `listing` | 仅 listing → short_answer |
| `qa` | 动态 / 定义类短答 |
| `follow_up_short` | 运营建议 / 指代追问 |
| `follow_up_upgrade` | 升级完整报告 → deep_full |
| `clarify` | 缺公司澄清 |
| `ambiguous` | 无信号不默认 Deep |
| `invalid_deixis` | 「它都」+ prior vs 坏 Memory |
| `memory_fill` | Memory 补全公司后短答 |
| `multi_step` | listing→analyze / collect→advise / collect→analyze |
| `oos` | 天气 / 请假邮件 |

### 门禁

| 指标 | 阈值 | 实测 |
|------|------|------|
| Critical accuracy | 100% | 20/20 |
| Overall accuracy | ≥ 95% | 20/20 = 100% |

## 4. 修改了哪些模块

| 路径 | 说明 |
|------|------|
| `decision_e2e_eval.py` | 新增 |
| `e2e_decision_goldens.json` | 新增 |
| `e2e_decision_baseline_snapshot.json` | 新增 |
| `test_decision_e2e_phase7.py` | 新增 |
| `PHASE7_COMPLETION.md` | 本文件 |

## 5. 测试结果

```text
pytest …(Phase1–7 + Router/follow_up + dual listing)… -q
→ 106 passed
```

## 6. Regression 结果

| 门禁 | 结果 |
|------|------|
| E2E critical 100% | 通过 |
| E2E overall ≥ 95% | 通过 |
| 正反例 pair 完整 | 通过 |
| 既有 Phase1–6 / Router 金标 | 通过 |
| 默认 off 无行为变化 | 通过 |

## 7. 新发现的问题 / Follow-up

1. **仍不建议默认 `on`：** 需先 shadow 观察线上 `decision_stack` 一段时间。  
2. **multi_step 仍无逐步 runner：** E2E 只断言 Plan/Capability；真正 list→deep 串联执行仍是 Follow-up。  
3. **Legacy Intent LLM 未进本 Eval：** 金标用 `intent_override` 种子实体，避免 LLM 抖动；线上 LLM 漂移需另开评测。  
4. **套件可继续加厚：** 英文 CA、无 prior 的升级、Memory+CA 组合等。

## 8. 下一阶段建议

决策架构主线 Phase 0–7 已齐。可选后续：

1. **Shadow 观察期** → 再考虑默认 `DECISION_PLANNER_ROUTING=on`  
2. **Multi-step Executor**（按 `PlanStep` 逐步跑）  
3. **线上 shadow 日志汇总 / 准确率看板**

启用前自检：

```bash
cd backend && PYTHONPATH=. pytest tests/unit/test_decision_e2e_phase7.py -q
export DECISION_PLANNER_ROUTING=shadow   # 先观察
# 确认后再 on
```

---

## 范围核对

- [x] 全链路 E2E 金标覆盖计划所列场景类  
- [x] critical 100% / overall ≥ 95%  
- [x] 正反例成对（follow_up vs CA、listing vs combo、deixis）  
- [x] 基线快照冻结  
- [x] 完成清单中文交付  
- [x] **未**默认开启生产 Planner 路径  
