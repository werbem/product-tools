"""Demo mode data — 固定案例 "抖音(字节跳动) vs 快手" 竞品分析。

在 DEMO_MODE=true 且无 LLM API Key 时，提供完整的展示数据。
保留真实 Agent 创建流程，仅跳过 LLM/Tools 调用。
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

# ── 固定 demo 用例 ──

DEMO_CASE = {
    "our_company": "字节跳动",
    "competitor_company": "快手",
    "product": "抖音",
    "objective": "product_improvement",
}

# ── 完整 demo 分析数据 ──


def build_demo_plan() -> dict:
    return {
        "objective": "分析抖音与快手的产品竞争力差异，识别抖音可改进的功能与体验",
        "analysis_scope": ["positioning", "users", "features", "ux", "business", "technology", "growth"],
        "research_tasks": [
            {
                "task_id": "task_web_001",
                "source_type": "web",
                "keywords": ["抖音", "快手", "短视频", "DAU", "市场份额"],
                "priority": 5,
                "dependencies": [],
            },
            {
                "task_id": "task_as_001",
                "source_type": "app_store",
                "keywords": ["抖音", "App Store评分", "用户评价"],
                "priority": 4,
                "dependencies": [],
            },
            {
                "task_id": "task_news_001",
                "source_type": "news",
                "keywords": ["抖音 快手 竞争", "短视频 财报", "字节跳动 上市"],
                "priority": 3,
                "dependencies": ["task_web_001"],
            },
            {
                "task_id": "task_social_001",
                "source_type": "social",
                "keywords": ["抖音 直播", "快手 电商", "创作者生态"],
                "priority": 3,
                "dependencies": [],
            },
        ],
        "estimated_duration_minutes": 5,
    }


def build_demo_evidence() -> dict:
    return {
        "sources": [
            {
                "source_id": "src_001",
                "source_type": "web",
                "title": "QuestMobile 2025 短视频行业报告",
                "url": "https://example.com/questmobile-2025",
                "summary": "抖音月活7.2亿，快手月活4.8亿；抖音用户日均使用时长128分钟，快手112分钟",
                "confidence": "verified",
                "published_date": "2025-06",
            },
            {
                "source_id": "src_002",
                "source_type": "app_store",
                "title": "抖音 App Store 评价分析",
                "url": "https://example.com/douyin-appstore",
                "summary": "评分4.7/5，近30天新增评价12万条。正面反馈集中在推荐算法精准、内容丰富；负面反馈集中在广告增多、直播质量参差",
                "confidence": "verified",
                "published_date": "2025-07",
            },
            {
                "source_id": "src_003",
                "source_type": "web",
                "title": "快手2024年财报分析",
                "url": "https://example.com/kuaishou-2024-report",
                "summary": "快手2024年营收1280亿元，同比增长12%；电商GMV达1.5万亿，直播收入占比持续下降，广告收入占比提升至52%",
                "confidence": "verified",
                "published_date": "2025-03",
            },
            {
                "source_id": "src_004",
                "source_type": "social",
                "title": "短视频创作者生态对比",
                "url": "https://example.com/creator-eco-comparison",
                "summary": "抖音头部创作者集中度高，快手腰部创作者生态更活跃。抖音创作者变现以广告为主，快手以直播打赏和电商为主",
                "confidence": "likely",
                "published_date": "2025-05",
            },
            {
                "source_id": "src_005",
                "source_type": "news",
                "title": "字节跳动2025战略调整：聚焦AI与电商",
                "url": "https://example.com/bytedance-2025-strategy",
                "summary": "字节跳动2025年重点投入AI搜索和AI推荐，抖音电商GMV目标3万亿。海外TikTok Shop增速超预期",
                "confidence": "verified",
                "published_date": "2025-06",
            },
            {
                "source_id": "src_006",
                "source_type": "web",
                "title": "快手AI大模型Kling在视频生成领域突破",
                "url": "https://example.com/kuaishou-kling",
                "summary": "快手的Kling视频生成模型在业界评测中表现优异，已应用于创作者工具和广告素材生成",
                "confidence": "likely",
                "published_date": "2025-07",
            },
        ],
        "total_found": 6,
        "research_summary": "共搜索到6条高质量证据，覆盖行业数据、财报、用户评价、创作者生态和AI技术等维度。数据来源包括第三方报告、官方财报和社区分析。",
    }


def build_demo_insights() -> dict:
    return {
        "key_findings": [
            {
                "dimension": "用户规模",
                "finding": "抖音月活7.2亿 vs 快手4.8亿，抖音领先50%。但快手在三四线城市渗透率更高(58% vs 45%)",
                "impact": "高",
                "confidence": "verified",
            },
            {
                "dimension": "商业变现",
                "finding": "快手电商GMV 1.5万亿，抖音电商目标3万亿。快手直播收入占比下降(从35%到22%)，广告收入占比上升至52%，与抖音趋同",
                "impact": "高",
                "confidence": "verified",
            },
            {
                "dimension": "AI技术",
                "finding": "快手Kling视频生成模型表现突出，抖音在推荐算法上仍有优势但AI视频生成领域相对落后",
                "impact": "中",
                "confidence": "likely",
            },
            {
                "dimension": "创作者生态",
                "finding": "抖音头部集中，快手腰部活跃。快手创作者对平台的粘性更强，抖音存在头部创作者流失风险",
                "impact": "中",
                "confidence": "likely",
            },
            {
                "dimension": "用户体验",
                "finding": "抖音推荐精准但广告增多引发用户不满；快手社区氛围更好但内容质量参差",
                "impact": "中",
                "confidence": "estimated",
            },
        ],
        "summary": "抖音在用户规模和推荐算法上保持领先，但在AI视频生成和创作者生态多样性方面存在差距。快手正通过Kling模型和社区运营缩小差距。",
    }


def build_demo_strategic() -> dict:
    return {
        "swot": {
            "strengths": ["推荐算法全球领先", "用户规模行业第一", "广告变现效率高", "内容供给丰富"],
            "weaknesses": ["AI视频生成能力不足", "创作者头部过度集中", "社区氛围弱于快手", "用户对广告疲劳感上升"],
            "opportunities": ["AI搜索和AI推荐升级", "抖音电商3万亿目标", "海外TikTok Shop协同", "AIGC内容创作工具"],
            "threats": ["快手Kling模型技术领先", "快手社区粘性更强", "视频号等新竞争者崛起", "监管政策不确定性"],
        },
        "recommendations": [
            {
                "title": "加大AI视频生成投入",
                "description": "对标快手Kling，建立抖音自有的AI视频生成能力。不仅用于创作者工具，也可融入推荐系统的内容理解",
                "priority": "P0",
            },
            {
                "title": "优化创作者生态多样性",
                "description": "建立腰部创作者扶持计划，降低头部依赖。借鉴快手社区运营经验，提升创作者留存率",
                "priority": "P1",
            },
            {
                "title": "改善用户体验与广告平衡",
                "description": "优化广告投放频率和质量，增加用户对广告的自主控制能力。考虑推出轻量级广告订阅模式",
                "priority": "P1",
            },
            {
                "title": "加速电商与内容融合",
                "description": "利用AI推荐打通内容到电商的转化链，提升直播电商转化率。构建闭环的创作者-品牌-用户生态",
                "priority": "P0",
            },
        ],
    }


def build_demo_report_markdown() -> str:
    return """# 竞品分析报告：抖音 vs 快手 (2025年7月)

---

## 执行摘要

本报告对比分析了**抖音(字节跳动)** 与**快手**在用户规模、商业变现、AI技术、创作者生态和用户体验五个维度的竞争力差异。

**核心结论：** 抖音在用户规模和推荐算法上保持领先，但在AI视频生成（快手Kling模型）和创作者生态多样性方面存在差距。建议P0优先级投入AI视频生成和电商闭环建设。

---

## 1. 市场概览

| 维度 | 抖音 | 快手 | 差距 |
|------|------|------|------|
| **月活用户** | 7.2亿 | 4.8亿 | +50% |
| **日均使用时长** | 128分钟 | 112分钟 | +14% |
| **三四线渗透率** | 45% | 58% | -13% |
| **电商GMV目标** | 3万亿 | 1.5万亿 | +100% |

> 数据来源：QuestMobile 2025、快手2024年报

---

## 2. 多维度对比分析

### 2.1 用户规模与增长

- **抖音** 月活7.2亿，保持增长但增速放缓（YOY +6%）
- **快手** 月活4.8亿，三四线市场优势明显
- **关键发现**：快手下沉市场用户粘性更强，抖音一二线用户消费力更高

### 2.2 商业变现能力

- **抖音**：广告收入占比60%+，电商GMV目标3万亿（2025），直播电商增速显著
- **快手**：广告收入占比提升至52%，直播收入占比降至22%，电商GMV达1.5万亿
- **趋势**：两者商业模式趋同，都以广告+电商双轮驱动

### 2.3 AI技术对比

| 能力 | 抖音/字节 | 快手 |
|------|-----------|------|
| 推荐算法 | ★★★★★（全球领先） | ★★★★ |
| AI视频生成 | ★★★ | ★★★★★（Kling模型） |
| AI搜索 | ★★★★（豆包/搜索） | ★★★ |
| 多模态理解 | ★★★★ | ★★★★ |

### 2.4 创作者生态

- **抖音**：头部创作者集中（Top1%贡献40%内容消费），变现以广告和品牌合作为主
- **快手**：腰部创作者更活跃，社区氛围好，变现以直播打赏和电商为主
- **风险**：抖音头部创作者存在被快手或其他平台挖角的风险

### 2.5 用户体验

- **抖音**：推荐精准、内容丰富，但广告增多（每5条1条广告）引发用户不满
- **快手**：社区互动氛围好，评论质量高，但内容质量参差不齐

---

## 3. SWOT分析

### 抖音

| 优势 (S) | 劣势 (W) |
|----------|----------|
| 推荐算法全球领先 | AI视频生成能力不足 |
| 用户规模行业第一 | 创作者头部过度集中 |
| 广告变现效率高 | 社区氛围弱于快手 |
| 内容供给丰富 | 用户对广告疲劳感上升 |

| 机会 (O) | 威胁 (T) |
|----------|----------|
| AI搜索和AI推荐升级 | 快手Kling模型技术领先 |
| 电商3万亿目标 | 快手社区粘性更强 |
| 海外TikTok Shop协同 | 视频号等新竞争者崛起 |
| AIGC内容创作工具 | 监管政策不确定性 |

---

## 4. 战略建议

### P0 - 紧急（本季度）

1. **加大AI视频生成投入**
   - 对标快手Kling，建立抖音自有AI视频生成能力
   - 应用场景：创作者工具 → 广告素材生成 → 内容理解增强
   - 预期收益：创作者生产效率提升2-3倍

2. **加速电商闭环建设**
   - 打通AI推荐-内容-电商转化链
   - 提升直播电商转化率（当前约3%，目标5%）
   - 构建创作者-品牌-用户三方生态闭环

### P1 - 重要（半年内）

3. **优化创作者生态多样性**
   - 建立腰部创作者扶持计划（每月100万+现金激励）
   - 借鉴快手社区运营经验，设置"粉丝亲密度"体系
   - 降低头部创作者流失风险

4. **改善用户体验与广告平衡**
   - 上线广告频次智能控制（AI根据用户行为动态调整）
   - 推出轻量级广告订阅模式（月费15元去广告）
   - 增强用户对广告类型的偏好设置

---

## 5. 风险提示

1. **技术风险**：快手Kling模型若持续领先，可能改变短视频内容供给格局
2. **市场风险**：视频号等新平台可能分流用户，特别是在微信生态内
3. **监管风险**：短视频和直播电商领域的监管趋严，需关注合规成本
4. **人才风险**：AI核心人才竞争激烈，需加强招聘和留任策略

---

## 6. 数据来源

| 来源 | 置信度 | 日期 |
|------|--------|------|
| QuestMobile 2025报告 | verified | 2025-06 |
| 抖音App Store评价 | verified | 2025-07 |
| 快手2024年报 | verified | 2025-03 |
| 创作者生态分析 | likely | 2025-05 |
| 字节跳动战略分析 | verified | 2025-06 |
| 快手Kling评测 | likely | 2025-07 |

---

*报告生成于2025年7月，数据可能随时间变化。本报告仅供内部决策参考。*
"""


def build_demo_review_result() -> dict:
    return {
        "overall_score": 8.5,
        "passed": True,
        "issues": [
            {
                "severity": "MEDIUM",
                "description": "三四线渗透率数据为估算值，建议获取精确实数后更新",
                "suggestion": "引入QuestMobile或极光大数据API获取精确实时数据",
            },
            {
                "severity": "LOW",
                "description": "AI技术对比部分缺少抖音AIGC的具体产品数据",
                "suggestion": "后续迭代补充抖音Dreamina等AIGC产品数据",
            },
        ],
        "high_count": 0,
        "deletion_suggestions": [],
    }


def build_demo_full_state(task_id: str) -> dict:
    """构建完整的 demo state，跳过所有 agent 调用。"""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "task_id": task_id,
        "created_at": now,
        "updated_at": now,
        "user_input": DEMO_CASE,
        "validated_input": {
            "is_valid": True,
            **DEMO_CASE,
        },
        "current_phase": "completed",
        "progress": 100.0,
        "phase_history": [
            {"phase": "validated", "entered_at": now, "duration_ms": 50, "status": "completed"},
            {"phase": "planned", "entered_at": now, "duration_ms": 100, "status": "completed"},
            {"phase": "researched", "entered_at": now, "duration_ms": 200, "status": "completed"},
            {"phase": "compared", "entered_at": now, "duration_ms": 150, "status": "completed"},
            {"phase": "insighted", "entered_at": now, "duration_ms": 150, "status": "completed"},
            {"phase": "strategized", "entered_at": now, "duration_ms": 100, "status": "completed"},
            {"phase": "reported", "entered_at": now, "duration_ms": 200, "status": "completed"},
            {"phase": "reviewed", "entered_at": now, "duration_ms": 100, "status": "completed"},
        ],
        "research_plan": build_demo_plan(),
        "evidence_bundle": build_demo_evidence(),
        "gap_analysis": {"gaps": [], "has_gaps": False},
        "insights": build_demo_insights(),
        "strategic_insights": build_demo_strategic(),
        "report_document": {
            "formats": {
                "markdown": build_demo_report_markdown(),
                "html": None,
                "docx_url": None,
            },
            "sections": [],
            "metadata": {
                "total_word_count": len(build_demo_report_markdown().split()),
                "generated_at": now,
            },
            "title": "竞品分析报告：抖音 vs 快手",
        },
        "review_result": build_demo_review_result(),
        "errors": [],
        "stream_events": [],
        "human_checkpoints": [],
        "pending_human_decision": None,
        "final_report": {
            "formats": {
                "markdown": build_demo_report_markdown(),
                "word_url": None,
                "html": None,
            },
            "sections": [],
            "metadata": {
                "total_word_count": len(build_demo_report_markdown().split()),
            },
        },
        "total_duration_ms": 1250,
        "llm_token_usage": {"total_prompt_tokens": 0, "total_completion_tokens": 0},
        "version": "v1",
        "demo": True,
    }
