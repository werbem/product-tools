# Phase 3 完成清单（中文）

**项目：** Agent 决策架构重构  
**阶段：** Phase 3 — Entity Extraction  
**完成日期：** 2026-09-06  
**是否切换生产路径：** **否**（独立 Entity 门面 + 金标；会话主路径未接入）

---

## 1. 修改了什么

- 新增 [`decision_entity_extractor.py`](../../backend/app/application/services/decision_entity_extractor.py)
  - 封装 `intent_entities` + prior / Memory / curated
  - 输出 `DecisionEntities`，每槽带 `source` + `confidence`
  - 支持列表主语、A和B/vs 对、代词列表回退 prior/memory
  - 拒绝无效公司（如 Memory 中的「它都」）
  - 可选 curated peers 填充（**不触发** Workflow）
  - `entities_imply_launch(...)` 恒为 `False`（不变量）
- 新增 Entity 金标 [`entity_goldens.json`](../../backend/tests/fixtures/entity_goldens.json)
- 新增单测 [`test_decision_entity_phase3.py`](../../backend/tests/unit/test_decision_entity_phase3.py)

## 2. 没有修改什么

- `ConversationService` / 生产 Router 主路径（未接线）
- Intent LLM、Deep、Research、Memory 存储、UI、数据库
- Phase 0 Router 金标期望值

## 3. 新增了什么 Contract / 能力

沿用 Phase 1 `DecisionEntities` / `EntitySlot`。

**填充优先级（公司）：**

1. 消息列表主语（`extract_listing_subject_company`）  
2. 消息中的 A和B / vs 对  
3. 当前轮 legacy intent（标为 `message`）  
4. prior  
5. memory（经 `sanitize_company_name`）  
6. 代词列表且主语为空 → prior / memory  

**竞品：** message/vs → legacy → prior → memory → curated（`resolve_competitor_suggestions`）

**原则：** 槽位填满 ≠ 启动 Deep。

## 4. 修改了哪些模块

| 路径 | 说明 |
|------|------|
| `backend/app/application/services/decision_entity_extractor.py` | 新增 |
| `backend/tests/fixtures/entity_goldens.json` | 新增 |
| `backend/tests/unit/test_decision_entity_phase3.py` | 新增 |
| `docs/decision-architecture/PHASE3_COMPLETION.md` | 本文件 |

## 5. 测试结果

```text
pytest tests/unit/test_decision_entity_phase3.py \
  tests/unit/test_decision_intent_phase2.py \
  tests/unit/test_decision_contracts_phase1.py \
  tests/unit/test_router_goldens_pr_v26.py \
  tests/unit/test_router_service_pr_v21.py \
  tests/unit/test_intent_mapper_routing.py \
  tests/unit/test_follow_up_service.py \
  -q
→ 70 passed
```

## 6. Regression 结果

| 门禁 | 结果 |
|------|------|
| Router critical / overall | 通过 |
| Intent Phase 2 金标 | 通过 |
| Entity critical 金标 | 通过 |
| Entity 不触发 launch 不变量 | 通过 |
| Entity 抽取不影响 Router 结果 | 通过 |

## 7. 新发现的问题 / Follow-up

1. **Legacy intent 与 message 双源：** 当前将 legacy 槽位标为 `message`；若 LLM 幻觉实体，需 Phase 4 Planner 用 Intent.task_family 约束，或增加 `source=inferred` 细分。  
2. **curated peers 在 Entity 层填充：** 方便后续 Planner，但必须坚持「不等于开跑」；切生产前应用 flag 控制是否预填。  
3. **未做时间范围完整 NER：** 仅规则匹配「近期/最近/…」。  
4. **未接入 ConversationService：** 线上「它都」修复仍依赖既有 sanitize；新抽取器待 Phase 4/5 统一使用。

## 8. 下一 Phase 建议

进入 **Phase 4 — Planner**：

- 输入：`DecisionIntent` + `DecisionEntities` + `DecisionContext`  
- 输出：`ExecutionPlan`（clarify / short_answer / research / deep_* / follow_up / oos）  
- **禁止隐式默认 Deep**  
- 仅 Shadow，不切生产  
- 规则必须带正反例金标  

**请确认后再批准 Phase 4。**

---

## 范围核对

- [x] Entity 不直接触发 Workflow  
- [x] 未切生产路径  
- [x] 未为架构问题往 Router 加语义正则  
- [x] 含代词列表正例 + 无效 Memory 公司反例相关覆盖  
- [x] 完成清单中文交付  
