"""Shared discourse / ask-form signal patterns for Decision Intent (Phase 2).

Canonical home for patterns previously duplicated inside RouterService.
Router may import these helpers; Intent extractor owns semantic interpretation.
Do not add new global semantic regex to Router — extend signals + extractor instead.
"""

from __future__ import annotations

import re

from app.application.services.intent_entities import looks_like_competitor_listing_query
from app.application.services.intent_mapper import (
    collection_primary_over_nested_analysis,
    detect_analysis_intent,
    detect_collection_intent,
    matched_analysis_signals,
    matched_collection_signals,
)

# Hard out-of-domain
OUT_OF_SCOPE_PATTERN = re.compile(
    r"天气|气温|下雨|几点|几点钟|星座|彩票|做饭|菜谱|"
    r"请假邮件|写.{0,8}请假|"
    r"how'?s\s+the\s+weather|what\s+time\s+is\s+it",
    re.IGNORECASE,
)

# Deixis / explicit continue-prior phrasing
FOLLOW_UP_DEIXIS_PATTERN = re.compile(
    r"基于刚才|根据上次|继续分析|接着刚才|补充一下|在此基础上|"
    r"刚才的报告|上一份|上一次|刚才的结果|基于上次|接着看|"
    r"基于这[个些]|基于此|根据这[个些]|根据以上|基于以上|基于上述|"
    r"据此|结合上面|结合以上|结合刚才|就这些信息|"
    r"继续[，,、]?把|"
    r"继续.{0,32}(?:完整(?:竞品分析)?报告|出报告|全面对比)|"
    r"based on (?:the )?(?:last|previous|this|these)|"
    r"based on (?:this|that) (?:info|information)|"
    r"follow[\s-]?up|continue from",
    re.IGNORECASE,
)

# Soft advice / next-step (needs prior for advise_prior family)
ADVICE_FOLLOW_UP_PATTERN = re.compile(
    r"下一步|接下来|该怎么做|应该做什么|应该怎么做|应该怎么|"
    r"怎么推进|如何推进|怎么提升|如何提升|怎么改进|如何改进|"
    r"怎么优化|如何优化|怎么加强|如何加强|怎么构建|如何构建|"
    r"有什么建议|给我(?:一些)?建议|行动建议|落地建议|怎么落地|"
    r"如果我是|假如我是|作为.{0,12}(?:产品|运营|市场|增长|策略)|"
    r"我该如何|我该怎么|我们该怎么|从运营角度|从产品角度|"
    r"用户体验|产品壁垒|护城河|怎么赢|如何赢|"
    r"what should i (?:do|focus)|next steps?|"
    r"how (?:can|should|do) (?:i|we)|recommendations?\b",
    re.IGNORECASE,
)

# Upgrade prior analysis to fuller report (discourse=upgrade_prior)
UPGRADE_PRIOR_PATTERN = re.compile(
    r"完整报告|继续出报告|全面对比|补充进报告|出一份完整|完整竞品分析|"
    r"完整对比报告|继续.{0,8}报告|生成完整报告|"
    r"full\s+report|complete\s+(?:comparison|report)",
    re.IGNORECASE,
)

LIGHT_QUERY_PATTERN = re.compile(
    r"(?:最近|近期).{0,16}(?:有什么|有哪些|什么变化|变化|动态|近况|新功能)|"
    r"(?:有什么变化|什么情况|近况如何|怎么样了|有哪些新功能)|"
    r"what(?:'s|\s+is)\s+new|recent\s+changes|what(?:'s|\s+is)\s+happening",
    re.IGNORECASE,
)

SIMPLE_QUESTION_PATTERN = re.compile(
    r"(?:是什么|是谁|什么意思|简单介绍|一句话|简要介绍|介绍一下)|"
    r"(?:大概是怎样|是怎样的|有哪些类型)|"
    r"(?:注意点|注意事项|要注意什么|有什么注意)|"
    r"(?:有哪些竞品|有什么竞品|对比了哪些竞品|竞品是谁)|"
    r"(?:常见)?竞品(?:公司)?.{0,4}(?:都)?有(?:哪些|什么)|有(?:哪些|什么).{0,6}(?:常见)?竞品|"
    r"(?:帮我)?(?:推荐|列出|找一下|说说).{0,12}竞品|"
    r"(?:吗？|吗\?)\s*$|"
    r"what\s+is|who\s+is|which\s+competitors|briefly|in\s+one\s+sentence",
    re.IGNORECASE,
)

EN_COLLECTION_PATTERN = re.compile(
    r"\b(?:collect|gather|research)\b.{0,48}"
    r"\b(?:info|information|intel|news|materials?|data)\b",
    re.IGNORECASE,
)

FOCUS_CLAUSE_PATTERN = re.compile(
    r"(?:重点(?:是|：|:)|focus(?:ing)?\s+on)\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def looks_like_out_of_scope(text: str) -> bool:
    return bool(text and OUT_OF_SCOPE_PATTERN.search(text))


def looks_like_follow_up_deixis(text: str) -> bool:
    return bool(text and FOLLOW_UP_DEIXIS_PATTERN.search(text))


def looks_like_advice_follow_up(text: str) -> bool:
    if not text or len(text) > 160:
        return False
    return bool(ADVICE_FOLLOW_UP_PATTERN.search(text))


def looks_like_upgrade_prior(text: str) -> bool:
    return bool(text and UPGRADE_PRIOR_PATTERN.search(text))


def looks_like_light_query(text: str) -> bool:
    if not text or len(text) > 120:
        return False
    return bool(LIGHT_QUERY_PATTERN.search(text))


def looks_like_simple_question(text: str) -> bool:
    if not text or len(text) > 100:
        return False
    return bool(SIMPLE_QUESTION_PATTERN.search(text))


def looks_like_en_collection(text: str) -> bool:
    return bool(text and EN_COLLECTION_PATTERN.search(text))


def extract_focus_clause(text: str) -> str | None:
    m = FOCUS_CLAUSE_PATTERN.search((text or "").strip())
    if not m:
        return None
    focus = (m.group(1) or "").strip().rstrip("。．.！!？?")
    return focus or None


def collect_debug_signals(text: str) -> list[str]:
    """Ordered debug tokens for DecisionIntent.signals (not for prod branching)."""
    out: list[str] = []
    if looks_like_out_of_scope(text):
        out.append("oos")
    if looks_like_follow_up_deixis(text):
        out.append("deixis")
    if looks_like_advice_follow_up(text):
        out.append("advice")
    if looks_like_upgrade_prior(text):
        out.append("upgrade")
    if detect_analysis_intent(text):
        out.extend(f"analysis:{s}" for s in matched_analysis_signals(text)[:5])
    if detect_collection_intent(text) or looks_like_en_collection(text):
        cols = matched_collection_signals(text)
        if looks_like_en_collection(text) and not cols:
            cols = ["en_collection"]
        out.extend(f"collection:{s}" for s in cols[:5])
    if looks_like_competitor_listing_query(text):
        out.append("listing")
    if looks_like_light_query(text):
        out.append("dynamics")
    if looks_like_simple_question(text):
        out.append("simple")
    if collection_primary_over_nested_analysis(text):
        out.append("collection_primary")
    return out
