"""Report Agent prompts — LLM-powered report generation.

The LLM's role is to ORGANIZE existing analysis into a well-formatted report.
It must NOT perform new analysis, fabricate data, or modify Strategy conclusions.
"""

from __future__ import annotations

from typing import Literal

SYSTEM_PROMPT = """你是一名专业的竞品分析报告撰写助手（Technical Writer）。

你的唯一职责：将已有的分析结果整理成结构清晰、格式规范的竞品分析报告。

## 核心原则

1. **只组织，不分析**：所有观点来自提供的证据和策略分析，不新增任何无来源的观点
2. **聚焦目标公司**：报告主体必须围绕我方公司和竞品公司展开，不得填充行业泛泛内容：所有观点来自提供的证据和策略分析，不新增任何无来源的观点
2. **数据标注规则**：
   - 来自公开来源的数据：标注“来源：[来源名称]”
   - 基于证据估算：标注“[估算]”
   - 基于有限证据推测：标注“[推测]”
   - 无可用数据：标注“暂无公开信息”
3. **引用证据**：每个关键论断后使用引用标记 [E001]、[E002] 等
4. **禁止编造**：不虚构任何公司名称、产品名称、数据、时间线
5. **保持原结论**：不修改、弱化或强化 Strategy Agent 的结论
6. **字数控制**：全文 3000-5000 字（不含表格和引用）
7. **表格换行**：Markdown 表格单元格内多条内容用「；」分隔，禁止输出 HTML `<br>` / `<br/>`
8. **项目记忆 / 企业笔记**：若用户消息含此类背景，仅作组织参考；引用笔记要点须标「（内部笔记）」；禁止伪造成 [E00x]

## 证据时效规则（Evidence Temporal Policy）

每条证据都带有 temporal_level 字段，取值与使用规则如下：

- **recent**：可用于所有章节
- **aging**：可用于市场趋势、竞争分析
- **stale**：降低引用优先级，不作为核心结论的唯一依据
- **historical**：只能用于「历史背景、市场演变、趋势变化」
  - 禁止用于：当前市场份额判断、当前竞争优势、当前产品能力评价、战略建议依据
- **unknown**：无法确定时效，引用时需谨慎，不作为核心结论的唯一依据

**硬性要求**：如果一个核心结论只有 historical 证据支持（缺少 recent/aging 证据），
必须在该结论后明确输出：
"缺少近3年数据验证，该结论存在时效风险"

### Gap 结论时效规则

- 每条 capability_gap 都带有 evidence_temporal_level 字段
- historical/stale 的 gap 结论不得作为当前竞争优势的唯一依据
- 如果核心判断只有低时效证据支持，需要提示数据验证风险

### Strategy 建议时效规则

- 每条 recommendation 都带有 evidence_temporal_level 字段
- historical/stale 的 recommendation 不得表达为确定性战略方向
- 战略建议中需要体现：「该建议基于低时效信息，需要结合近期数据验证」
- recent/aging/mixed/unknown 正常使用

## 输出格式

输出纯 Markdown，严格按照以下结构：

```
# 互联网产品竞品分析报告

> **我方**：[我方公司] | **竞品**：[竞品公司] | **产品**：[产品] | **日期**：[日期]

---

## 目录
1. Executive Summary
2. 产品概览与定位
3. 目标用户与画像
4. 核心功能对比
5. 用户体验与设计
6. 商业模式与收费
7. 技术架构与能力
8. 增长策略与市场
9. 竞争格局
10. SWOT 分析
11. 关键指标对比
12. 战略建议
13. 实施路线图

---

## 一、Executive Summary

[2-3 段概述：分析目标、核心发现、关键战略建议摘要。约 200-300 字]

---

## 二、产品概览与定位

| 维度 | 我方 | 竞品 |
|------|------|------|
| 产品名称 | [名称] | [名称] |
| 产品定位 | [定位] [E001] | [定位] [E002] |
| 核心价值主张 | [主张] | [主张] |
| 商业模式 | [模式] | [模式] |
| 覆盖市场 | [市场] | [市场] |

[定位差异分析段落，引用 evidence_refs]

---

## 三、目标用户与画像

[用户对比表格 + 分析段落，基于 evidence]

---

## 四、核心功能对比

[功能对比表格，从 feature_matrix 提取]

---

## 五、用户体验与设计

[基于 UX 相关 evidence 撰写]

---

## 六、商业模式与收费

[基于 business 相关 evidence 撰写]

---

## 七、技术架构与能力

[基于 technology/ai_capability 相关 evidence 撰写]

---

## 八、增长策略与市场

[基于 growth 相关 evidence 撰写]

---

## 九、竞争格局

[市场格局分析，包含市场份额数据，标注来源]

---

## 十、SWOT 分析

表格单元格内多条要点用中文分号「；」分隔，**禁止**使用 HTML `<br>` / `<br/>`（Markdown 表格无法渲染）。

|  | 优势 (S) | 劣势 (W) |
|------|------|------|
| **内部** | [Strength 1] [E001]；[Strength 2] [E002] | [Weakness 1] [E003]；[Weakness 2] [E004] |
| **外部** | [Opportunity 1] [E005]；[Opportunity 2] [E006] | [Threat 1] [E007]；[Threat 2] [E008] |

---

## 十一、关键指标对比

| 指标 | 我方 | 竞品 | 差距 | 证据 |
|------|------|------|------|------|
| [指标1] | [值] | [值] | [差距] | [E001] |
| [指标2] | [值] | [值] | [差距] | [E002] |

---

## 十二、战略建议

### 核心建议

对每个建议输出：
- **建议**：[行动标题]
- **理由**：[理由]
- **预期价值**：[预期价值]
- **优先级**：🔴 P0 / 🟠 P1 / 🟡 P2 / 🟢 P3
- **时间线**：立即 / 短期 / 中期 / 长期
- **关联证据**：[E001]

---

## 十三、实施路线图

### 短期（0-3月）
- [行动] - 目标：[目标] - 优先级：[P1]

### 中期（3-6月）
- [行动] - 目标：[目标] - 优先级：[P2]

### 长期（6-12月）
- [行动] - 目标：[目标] - 优先级：[P3]

---

## 附录

**数据来源**：[来源列表]
**证据质量**：总体 [X]% | 覆盖率 [Y]% | 新鲜度 [Z]%
**生成说明**：*本报告由 AI 竞品分析助手自动生成，数据来源已标注可信度。*
```

## 格式规范

- 表格使用 Markdown table 语法
- 引用使用 > blockquote
- 代码块用于技术指标
- 用 --- 分隔主要章节
- 引用标记格式：[E001]、[E002]
- 数据标注格式：来源：[来源名]、[估算]、[推测]、暂无公开信息
"""


ReportSegment = Literal[1, 2, 3]

# Segment → chapter titles (must align with SECTION_DEFS in report_agent.py)
SEGMENT_SECTION_TITLES: dict[ReportSegment, list[str]] = {
    1: [
        "一、Executive Summary",
        "二、产品概览与定位",
        "三、目标用户与画像",
        "四、核心功能对比",
    ],
    2: [
        "五、用户体验与设计",
        "六、商业模式与收费",
        "七、技术架构与能力",
        "八、增长策略与市场",
        "九、竞争格局",
    ],
    3: [
        "十、SWOT 分析",
        "十一、关键指标对比",
        "十二、战略建议",
        "十三、实施路线图",
    ],
}

SEGMENT_WORD_TARGETS: dict[ReportSegment, int] = {
    1: 800,
    2: 1000,
    3: 700,
}

_SEGMENT_FAST_NOTES: dict[ReportSegment, str] = {
    1: (
        "- **第四章「核心功能对比」**：仅基于 Evidence，按我方/竞品整理表格；"
        "关键结论标注 **[基于证据整理]**\n"
        "- 不得引用 gap.feature_matrix 或 strategy 输出\n"
    ),
    2: "- 中间分析章节仅基于 Evidence 组织，无数据时写「暂无公开信息」\n",
    3: (
        "- SWOT / 指标 / 战略 / 路线图基于 Evidence + 分析目标推导\n"
        "- 不得冒充 Gap/Strategy Agent 结论；标注 [基于证据整理] 或「暂无公开信息」\n"
    ),
}


def _objective_label(objective: str) -> str:
    objective_labels = {
        "product_improvement": "产品改进 — 对标竞品发现短板",
        "go_to_market": "市场进入 — 制定差异化策略",
        "investment_due_diligence": "投资尽调 — 评估竞争壁垒",
        "competitive_defense": "竞争防御 — 应对竞品进攻",
        "positioning_switch": "定位转型 — 重新定义定位",
        "partnership_evaluation": "合作评估 — 评估合作伙伴",
        "feature_benchmark": "功能对标 — 功能层面比较",
    }
    return objective_labels.get(objective, objective)


def build_report_prompt_segment(
    segment: ReportSegment,
    our_company: str,
    competitor_company: str,
    product: str,
    objective: str,
    evidence_json: str,
    gap_json: str,
    strategy_json: str,
    *,
    fast_mode: bool = True,
    previous_segments_summary: str | None = None,
    word_target: int | None = None,
    memory_notes_context: str | None = None,
) -> str:
    """Build prompt for one fast-mode report segment (subset of 13 chapters)."""
    from app.application.services.context_blocks import (
        REPORT_CONTEXT_RULES,
        append_context_to_prompt,
    )

    titles = SEGMENT_SECTION_TITLES[segment]
    target = word_target or SEGMENT_WORD_TARGETS[segment]
    chapters_list = "\n".join(f"- ## {t}" for t in titles)
    prev_block = ""
    if previous_segments_summary:
        prev_block = f"""
## 已完成章节摘要（供上下文衔接，勿重复输出）

{previous_segments_summary}
"""

    fast_note = _SEGMENT_FAST_NOTES.get(segment, "") if fast_mode else ""

    prompt = f"""## 任务信息
- **我方公司**：{our_company}
- **竞品公司**：{competitor_company}
- **比对产品**：{product}
- **分析目标**：{_objective_label(objective)}
- **模式**：快速模式 · 分段 {segment}/3
- **本段字数建议**：约 {target} 字

## 采集证据（Evidence）

{evidence_json}

## 差距分析（Gap Analysis）

{gap_json}

## 战略分析（Strategy）

{strategy_json}
{prev_block}
## 本段任务（仅输出以下章节）

**重要**：只输出下列章节，使用 `## 二级标题`，不要输出报告封面、目录或其他段章节。

{chapters_list}

### 快速模式约束
{fast_note}- 只使用 Evidence 中的数据，禁止编造
- 无数据时写「暂无公开信息」
- 每个关键论断后引用 [E001] 等证据标记
- 不要输出 ``` 代码围栏包裹全文

请生成本段 Markdown 内容。
"""
    return append_context_to_prompt(
        prompt, memory_notes_context, rules=REPORT_CONTEXT_RULES,
    )

def build_report_prompt(
    our_company: str,
    competitor_company: str,
    product: str,
    objective: str,
    evidence_json: str,
    gap_json: str,
    strategy_json: str,
    *,
    fast_mode: bool = False,
    compact_report: bool = False,
    strategy_is_stub: bool = False,
    gap_is_stub: bool = False,
    memory_notes_context: str | None = None,
) -> str:
    """Build the report generation prompt with all input data."""
    from app.application.services.context_blocks import (
        REPORT_CONTEXT_RULES,
        append_context_to_prompt,
    )

    obj_label = _objective_label(objective)
    fast_instructions = ""
    if fast_mode:
        fast_instructions = """
## 快速模式说明（Fast Mode）

本任务为**快速模式**：未执行 Compare / Insight / Strategy Agent，Gap 与 Strategy 输入为空。
你必须仍输出**完整 13 章**结构（与标准模板一致），不得省略章节。

### 对比与战略章节规则
- **第四章「核心功能对比」**：仅基于 Evidence，按我方/竞品并列整理表格；关键结论标注 **[基于证据整理]**
- **第十至十三章（SWOT / 指标 / 战略 / 路线图）**：基于 Evidence + 分析目标推导；不得冒充 Gap/Strategy Agent 的结构化输出
- 无足够证据时写「暂无公开信息」，禁止编造
- 全文控制在 **2500–3000 字**（不含表格与引用）
- 附录「生成说明」必须包含：
  *快速模式：未执行对比/洞察/战略分析，对比章节基于证据整理。*

### 禁止事项
- 不得引用不存在的 gap.differences / feature_matrix / strategy.recommendations
- 不得伪造 Compare 或 Strategy Agent 的结论来源
"""

    word_limit = "2500-3000" if fast_mode else ("2500-3000" if compact_report else "3000-4000")
    compact_note = ""
    if compact_report and not fast_mode:
        compact_note = """
## 总预算紧凑模式
工作流已接近 720s 总预算上限，请优先输出完整 13 章骨架，每章内容精简，控制在 **2500–3000 字**。
"""
    stub_instructions = ""
    if strategy_is_stub and not fast_mode:
        stub_instructions += """
## Strategy Stub 使用规则（超时降级）
Strategy 输入的 `swot_source`/`strategy_fallback` 为 **evidence_stub**（或 partial_json）。
- 第十至十三章必须**直接使用** Strategy JSON 中的 swot / recommendations
- 章首仅加一行说明：「非完整 Strategy Agent 输出，由证据摘要生成」
- **禁止**另行编写第二套「参考性 SWOT」或再次从 Evidence 重写战略章节
"""
    if gap_is_stub and not fast_mode:
        stub_instructions += """
## Gap Stub 使用规则（超时降级）
Gap 输入的 `compare_fallback` 为 **evidence_stub**（或 partial_json）。
- 对比相关章节优先使用 Gap JSON 中的 feature_matrix / capability_gaps
- 章首可一行说明：「非完整 Compare Agent 输出」
- 不要假装这是完整差距分析
"""

    if fast_mode:
        strategy_reminder = "- 对比/战略内容仅来自 Evidence，标注 [基于证据整理] 或「暂无公开信息」\n"
    elif strategy_is_stub:
        strategy_reminder = (
            "- Strategy 为 evidence_stub/partial：直接使用其 SWOT/建议，"
            "禁止二次「参考性编造」\n"
        )
    else:
        strategy_reminder = "- 保持 Strategy 结论不变\n"

    return append_context_to_prompt(
        f"""## 任务信息
- **我方公司**：{our_company}
- **竞品公司**：{competitor_company}
- **比对产品**：{product}
- **分析目标**：{obj_label}
- **日期**：今天
- **模式**：{"快速模式（Fast）" if fast_mode else "标准模式"}

## 采集证据（Evidence）

以下是从公开来源采集的证据，请只引用这些证据中的数据：
{evidence_json}

## 差距分析（Gap Analysis）

以下是与竞品的差距分析结果：
{gap_json}

## 战略分析（Strategy）

以下是战略分析结果：
{strategy_json}
{fast_instructions}{stub_instructions}{compact_note}
## 任务

请根据以上所有数据，按照输出格式模板，生成一份完整的竞品分析 Markdown 报告。

重要提醒：
- 只使用提供的数据，不编造任何信息
- 所有数据标注来源或标记为 [估算]/[推测]/暂无公开信息
{strategy_reminder}- 严格遵守「证据时效规则」：historical 证据只能用于历史背景/市场演变/趋势变化，不得作为当前市场份额、竞争优势、产品能力评价或战略建议的依据
- 如果核心结论只有 historical 证据支持，必须输出「缺少近3年数据验证，该结论存在时效风险」
- 报告控制在 {word_limit} 字
- 严格使用 Markdown 格式
""",
        memory_notes_context,
        rules=REPORT_CONTEXT_RULES,
    )