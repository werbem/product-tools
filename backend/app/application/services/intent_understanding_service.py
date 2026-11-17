"""Intent understanding service."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re

from app.application.dto.intent_dto import (
    IntentLLMOutput,
    IntentUnderstandingRequest,
    IntentUnderstandingResult,
)
from app.application.services.intent_mapper import (
    detect_analysis_intent,
    detect_collection_intent,
)
from app.application.services.intent_entities import (
    extract_listing_subject_company,
    infer_default_product,
    is_invalid_company_entity,
    is_placeholder_entity,
    is_same_brand_entity,
    looks_like_competitor_listing_query,
    sanitize_company_name,
    sanitize_competitors,
)
from app.infrastructure.agents.intent_prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.infrastructure.llm.client import LLMClient, llm_client

# Back-compat aliases used by conversation_service / tests
_is_placeholder_entity = is_placeholder_entity
_sanitize_competitors = sanitize_competitors

logger = logging.getLogger(__name__)

# Short interactive timeout — keep Intent off the Deep Research/Report LLM queue.
# Override via INTENT_LLM_TIMEOUT_S (seconds). Does not change workflow node budgets.
def _intent_llm_timeout_s() -> float:
    raw = os.getenv("INTENT_LLM_TIMEOUT_S", "20")
    try:
        return max(5.0, min(float(raw), 60.0))
    except (TypeError, ValueError):
        return 20.0

# Ordered by length desc so longer names match first (e.g. 拼多多 before 拼)
_PRODUCT_HINTS = (
    (r"下沉市场|电商", "电商下沉市场"),
    (r"酒店|住宿|OTA", "酒店"),
    (r"短视频", "短视频"),
    (r"直播", "直播电商"),
    (r"外卖|到家", "外卖"),
    (r"出行|打车|网约车", "出行"),
    (r"支付", "支付"),
    (r"社交", "社交"),
    (r"抖音", "抖音"),
    (r"全景|运动相机|action\s*cam|insta\s*360|影石|大疆|gopro", "运动相机/全景相机"),
)

# Expand known brands used in peer extraction / heuristics
_KNOWN_COMPANIES = (
    # Longer brand+product forms first so they win over short stems
    "美团外卖",
    "京东外卖",
    "抖音外卖",
    "饿了么",
    "拼多多",
    "美团",
    "携程",
    "飞猪",
    "抖音",
    "快手",
    "淘宝",
    "天猫",
    "京东",
    "微信",
    "支付宝",
    "字节跳动",
    "阿里巴巴",
    "腾讯",
    "百度",
    "小红书",
    "哔哩哔哩",
    "B站",
    "网易",
    "华为",
    "小米",
    "大疆",
    "DJI",
    "影石",
    "Insta360",
    "insta360",
    "GoPro",
    "得力",
    "晨光",
)


def _is_intelligence_collection(text: str) -> bool:
    """Heuristic for intel path in understanding — analysis signals win."""
    if detect_analysis_intent(text):
        return False
    return detect_collection_intent(text)

def _normalize_intel_entities(
    raw_message: str,
    company: str | None,
    product: str | None,
) -> tuple[str | None, str | None]:
    """Map phrases like 字节跳动抖音产品 -> company/product."""
    names = _extract_companies_in_order(raw_message)
    if "字节跳动" in names and "抖音" in names:
        company = company or "字节跳动"
        product = product or "抖音"
    elif "抖音" in names and not product:
        product = "抖音"
        if not company:
            company = "字节跳动"
    elif "快手" in names and not product:
        product = "快手"
    return company, product


def _extract_companies_in_order(text: str) -> list[str]:
    hits: list[tuple[int, str]] = []
    for name in _KNOWN_COMPANIES:
        start = 0
        while True:
            idx = text.find(name, start)
            if idx < 0:
                break
            hits.append((idx, name))
            start = idx + len(name)
    # Prefer earlier position, then longer name (美团外卖 over 美团)
    hits.sort(key=lambda x: (x[0], -len(x[1])))
    seen_spans: list[tuple[int, int]] = []
    ordered: list[str] = []
    seen_names: set[str] = set()
    for idx, name in hits:
        end = idx + len(name)
        if any(not (end <= s or idx >= e) for s, e in seen_spans):
            continue
        if name in seen_names:
            continue
        seen_names.add(name)
        seen_spans.append((idx, end))
        ordered.append(name)
    return ordered


def _infer_product(text: str) -> str | None:
    for pattern, label in _PRODUCT_HINTS:
        if re.search(pattern, text):
            return label
    return None


_LEADING_COMPARE_VERB_RE = re.compile(
    r"^(?:请|帮我|麻烦)?(?:完成|做一下|做|进行)?"
    r"(?:对比|对标|比较|对照)\s*"
)

# 「为什么飞猪…？请对比美团与携程」— subject before 对比, peers after
_SUBJECT_THEN_COMPARE_RE = re.compile(
    r"(?:请|帮我|麻烦)?(?:对比|对标|比较|对照)\s*",
)


def _strip_leading_compare_verb(name: str) -> str:
    text = (name or "").strip()
    text = _LEADING_COMPARE_VERB_RE.sub("", text).strip(" ，,、的")
    # Glued verb without separator:「对比美团」→「美团」
    text = re.sub(r"^(?:对比|对标|比较|对照)", "", text).strip(" ，,、的")
    return text


def _extract_subject_and_compare_peers(text: str) -> tuple[str | None, list[str]]:
    """『为什么飞猪酒旅…？请对比美团与携程』→ (飞猪, [美团, 携程])."""
    if not text:
        return None, []
    m = _SUBJECT_THEN_COMPARE_RE.search(text)
    if not m:
        return None, []
    before = text[: m.start()]
    after = text[m.end() :]
    # Need a real subject clause before the compare verb (avoid bare「对比A和B」)
    if not before.strip() or len(before.strip()) < 2:
        return None, []
    # Classic「A对比B」is handled by peer-pair patterns. This path is for
    # subject-then-compare-targets:「…？请对比美团与携程」or multi-peer lists.
    has_please_compare = bool(
        re.search(r"(?:请|帮我|麻烦).{0,6}(?:对比|对标|比较|对照)", text)
    )
    has_clause_break = bool(re.search(r"[？?！!。；;]", before))
    has_multi_peer = bool(re.search(r"(?:与|和|、|,|，)", after))
    if not (has_please_compare or has_clause_break or has_multi_peer):
        return None, []
    subjects = _extract_companies_in_order(before)
    peers = _extract_companies_in_order(after)
    if not subjects or not peers:
        return None, []
    subject = subjects[0]
    peers = [p for p in peers if p != subject]
    if not peers:
        return None, []
    return subject, peers


def _extract_peer_pair_from_text(text: str) -> tuple[str | None, str | None]:
    """Extract A/B from『A对比B』/『A vs B』 even when brands are unknown/Latin."""
    if not text:
        return None, None
    patterns = (
        r"([A-Za-z0-9][A-Za-z0-9 ._\-]{0,30}?)\s*(?:对比|VS|vs\.?|Vs)\s*"
        r"([\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._\-]{0,30})",
        # A对比B — separator must be 对比/VS (not bare 与/和, which matches「对比美团与携程」)
        r"([\u4e00-\u9fff]{2,12}?)\s*(?:对比|VS|vs\.?|Vs)\s*"
        r"([\u4e00-\u9fff]{2,12})",
        # A与B / A和B only when followed by 竞品|对比|差异 (classic pair ask)
        r"([\u4e00-\u9fff]{2,12})\s*(?:与|和)\s*"
        r"([\u4e00-\u9fff]{2,12})"
        r"(?:的|做|进行)?(?:竞品|对比|差异)",
        r"([A-Za-z0-9][A-Za-z0-9 ._\-]{0,30}?)\s*(?:与|和)\s*"
        r"([\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9 ._\-]{0,20}?)"
        r"(?:的|做|进行)?(?:竞品|对比|差异)",
    )
    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        a = re.sub(r"\s+", " ", m.group(1)).strip(" ，,、的")
        b = re.sub(r"\s+", " ", m.group(2)).strip(" ，,、的")
        # strip trailing verbs glued to B
        b = re.sub(r"(?:做|进行)?竞品分析(?:报告)?$", "", b).strip(" ，,、的")
        a = re.sub(r"(?:做|进行)?竞品分析(?:报告)?$", "", a).strip(" ，,、的")
        # Prefer company token after leading verbs:「帮我完成携程」→「携程」
        a = re.sub(r"^(?:帮我|请|麻烦)?(?:完成|做一下|做|进行)?", "", a).strip(" ，,、的")
        a = _strip_leading_compare_verb(a)
        b = _strip_leading_compare_verb(b)
        if _is_placeholder_entity(a) or _is_placeholder_entity(b):
            continue
        if is_invalid_company_entity(a) or is_invalid_company_entity(b):
            continue
        if a and b and a.lower() != b.lower():
            return a, b
    return None, None


def _resolve_peer_comparison(
    company: str | None,
    competitors: list[str],
    product: str | None,
    raw_message: str,
) -> tuple[str | None, list[str], str | None]:
    """Fill company/competitors/product for peer A-vs-B queries.

    Explicit A/B surface forms in the *current* message (「A和B」「A对比B」)
    always win over stale Memory / partial competitors.
    """
    names = _extract_companies_in_order(raw_message)
    comps = list(competitors)
    company = sanitize_company_name(_strip_leading_compare_verb(company or "")) or None
    comps = [
        c
        for c in (_strip_leading_compare_verb(str(c or "")) for c in comps)
        if c
    ]

    # 1) Subject +「请对比A与B」— company is subject, peers are compare targets
    subject, compare_peers = _extract_subject_and_compare_peers(raw_message or "")
    if subject and compare_peers:
        company = subject
        comps = list(compare_peers)
        if not product:
            product = _infer_product(raw_message)
        return company, comps, product

    # 2) Prefer explicit A-vs-B surface form (handles Latin brands + spaced names)
    peer_a, peer_b = _extract_peer_pair_from_text(raw_message or "")
    if peer_a and peer_b:
        # Current-message peer pair is authoritative — do not keep Memory peers.
        company = peer_a
        comps = [peer_b] if peer_b != peer_a else []
        if not product:
            product = _infer_product(raw_message)
        return company, comps, product

    if not company:
        if comps:
            # LLM put everyone in competitors — promote first as company
            company = comps[0]
            comps = comps[1:]
        elif len(names) >= 2:
            company = names[0]
            comps = names[1:]
        elif len(names) == 1:
            company = names[0]

    if company and not comps and len(names) >= 2:
        comps = [n for n in names if n != company]

    # Drop duplicates / self from competitors
    if company:
        comps = [c for c in comps if c != company]

    if not comps and len(names) >= 2 and company:
        comps = [n for n in names if n != company]

    if not product:
        product = _infer_product(raw_message)

    return company, comps, product


class IntentUnderstandingService:
    def __init__(self, llm_client_param: LLMClient | None = None) -> None:
        self._llm = llm_client_param or llm_client

    async def understand(self, request: IntentUnderstandingRequest) -> IntentUnderstandingResult:
        partial = request.partial
        merged_message = request.message
        if partial and partial.company:
            merged_message = f"{partial.company}相关：{request.message}"

        # 「拼多多的竞品有哪些」— subject is rule-extractable; skip Intent LLM
        # so listing answers are not blocked by a 20s intent timeout.
        # 「它都有哪些竞品」has no brand subject — reuse prior company from partial.
        if looks_like_competitor_listing_query(request.message):
            subject = extract_listing_subject_company(request.message)
            if not subject and partial:
                subject = sanitize_company_name(partial.company)
            if subject:
                product = _infer_product(request.message)
                if partial and not product:
                    product = partial.product
                if not product or is_same_brand_entity(product, subject):
                    product = infer_default_product(subject) or product
                return IntentUnderstandingResult(
                    type="competitive_analysis",
                    company=subject,
                    competitors=[],
                    product=product,
                    objective=partial.objective if partial else None,
                    confidence=0.88,
                    missing_fields=[],
                    needs_clarification=False,
                    clarification_question=None,
                    raw_message=request.message,
                )

        # 「用这些竞品做分析」with prior company+peers — skip Intent LLM (avoids 20s timeout)
        if (
            partial
            and partial.company
            and (partial.competitors or [])
            and (
                "用这些竞品" in (request.message or "")
                or detect_analysis_intent(request.message)
            )
            and len((request.message or "").strip()) <= 40
        ):
            product = (
                _infer_product(request.message)
                or partial.product
                or infer_default_product(partial.company)
            )
            comps = _sanitize_competitors(list(partial.competitors or []), partial.company)
            missing: list[str] = []
            if not product:
                missing.append("product")
            return IntentUnderstandingResult(
                type="competitive_analysis",
                company=partial.company,
                competitors=comps,
                product=product,
                objective=partial.objective,
                confidence=max(float(partial.confidence or 0.7), 0.85),
                missing_fields=missing,
                needs_clarification=bool(missing),
                clarification_question=(
                    "请告诉我要分析的具体产品或市场是什么？" if missing else None
                ),
                raw_message=request.message,
            )

        try:
            llm_output = await self._call_llm(merged_message, partial)
            result = self._build_result(llm_output, request.message, partial)
            return result
        except asyncio.TimeoutError:
            logger.warning(
                "intent_timeout conversation_id=%s timeout_s=%s",
                request.conversation_id,
                _intent_llm_timeout_s(),
            )
            # Conservative rule/heuristic only — never invent a silent Deep launch path.
            result = self._heuristic_result(request.message, partial)
            return result
        except Exception as exc:
            logger.warning(
                "intent_fallback conversation_id=%s err=%s",
                request.conversation_id,
                f"{type(exc).__name__}: {exc}",
            )
            result = self._heuristic_result(request.message, partial)
            return result

    async def _call_llm(
        self,
        message: str,
        partial: IntentUnderstandingResult | None,
    ) -> IntentLLMOutput:
        partial_text = json.dumps(partial.model_dump(), ensure_ascii=False) if partial else "无"
        user_prompt = USER_PROMPT_TEMPLATE.format(message=message, partial=partial_text)
        timeout_s = _intent_llm_timeout_s()
        response = await asyncio.wait_for(
            self._llm.generate(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=user_prompt,
                response_model=IntentLLMOutput,
                temperature=0.2,
                timeout=timeout_s,
            ),
            timeout=timeout_s + 2.0,
        )
        if response.parsed and isinstance(response.parsed, IntentLLMOutput):
            return response.parsed
        if response.content:
            # Client may surface timeouts as synthetic content
            if str(response.content).startswith("[TIMEOUT]"):
                raise asyncio.TimeoutError(response.content)
            data = json.loads(response.content)
            return IntentLLMOutput.model_validate(data)
        raise ValueError("empty LLM response")

    def _build_result(
        self,
        output: IntentLLMOutput,
        raw_message: str,
        partial: IntentUnderstandingResult | None,
    ) -> IntentUnderstandingResult:
        intel = _is_intelligence_collection(raw_message)

        if output.type == "unsupported" and intel:
            names = _extract_companies_in_order(raw_message)
            if names:
                output = IntentLLMOutput(
                    type="competitive_analysis",
                    company=names[0],
                    competitors=[],
                    product=_infer_product(raw_message),
                    objective="intelligence_collection",
                    confidence=max(output.confidence, 0.6),
                )
            else:
                return IntentUnderstandingResult(
                    type="unsupported",
                    confidence=output.confidence,
                    raw_message=raw_message,
                )
        elif output.type == "unsupported":
            # Analysis phrasing must not fall through to out_of_scope when LLM
            # fails to recognize lesser-known brands (e.g. Insta360 / 大疆).
            if detect_analysis_intent(raw_message):
                a, b = _extract_peer_pair_from_text(raw_message)
                names = _extract_companies_in_order(raw_message)
                output = IntentLLMOutput(
                    type="competitive_analysis",
                    company=a or (names[0] if names else None),
                    competitors=([b] if b else names[1:]),
                    product=_infer_product(raw_message),
                    objective=None,
                    confidence=max(float(output.confidence or 0.5), 0.55),
                )
            else:
                return IntentUnderstandingResult(
                    type="unsupported",
                    confidence=output.confidence,
                    raw_message=raw_message,
                )

        company = output.company or (partial.company if partial else None)
        competitors = list(output.competitors or (partial.competitors if partial else []))
        product = output.product or (partial.product if partial else None)
        objective = output.objective or (partial.objective if partial else None)

        company, competitors, product = _resolve_peer_comparison(
            company, competitors, product, raw_message,
        )
        # Explicit A-vs-B in this message: do not keep Memory/partial objective
        # (e.g. prior「华南市场趋势」bleeding into「滴滴和如祺」).
        peer_a, peer_b = _extract_peer_pair_from_text(raw_message or "")
        if peer_a and peer_b and not output.objective:
            objective = None
        company, product = _normalize_intel_entities(raw_message, company, product)
        if _is_placeholder_entity(company) or is_invalid_company_entity(company):
            company = sanitize_company_name(partial.company if partial else None)
        competitors = _sanitize_competitors(competitors, company)

        if intel:
            competitors = [
                c for c in competitors
                if c and c not in {company, product}
            ]

        missing: list[str] = []
        if not company:
            missing.append("company")
        # Asking「有哪些竞品」is itself the Q — do not treat empty peers as launch gaps
        if (
            not intel
            and not competitors
            and not looks_like_competitor_listing_query(raw_message)
        ):
            missing.append("competitors")
        if not product:
            product = infer_default_product(company)
        if not product:
            missing.append("product")

        needs_clarification = bool(missing)
        clarification = None
        if needs_clarification:
            if "company" in missing and "competitors" in missing:
                clarification = "请告诉我要对比的双方公司，例如：分析拼多多与淘宝的差异。"
            elif "company" in missing:
                clarification = "请告诉我您要分析哪家公司（分析公司）？"
            elif "competitors" in missing:
                clarification = "请告诉我主要对比哪些竞品？"
            elif "product" in missing:
                clarification = "请告诉我要分析的具体产品或市场是什么？"

        if intel and not objective:
            objective = "intelligence_collection"

        return IntentUnderstandingResult(
            type="competitive_analysis",
            company=company,
            competitors=competitors,
            product=product,
            objective=objective,
            confidence=output.confidence,
            missing_fields=missing,
            needs_clarification=needs_clarification,
            clarification_question=clarification,
            raw_message=raw_message,
        )

    def _heuristic_result(
        self,
        raw_message: str,
        partial: IntentUnderstandingResult | None,
    ) -> IntentUnderstandingResult:
        if partial:
            company, competitors, product = _resolve_peer_comparison(
                partial.company,
                list(partial.competitors or []),
                partial.product,
                raw_message,
            )
            company, product = _normalize_intel_entities(raw_message, company, product)
            if _is_placeholder_entity(company) or is_invalid_company_entity(company):
                company = None
            competitors = _sanitize_competitors(competitors, company)
            intel = _is_intelligence_collection(raw_message)
            missing: list[str] = []
            if not company:
                missing.append("company")
            if (
                not intel
                and not competitors
                and not looks_like_competitor_listing_query(raw_message)
            ):
                missing.append("competitors")
            if not product:
                product = infer_default_product(company)
            if not product:
                missing.append("product")
            peer_a, peer_b = _extract_peer_pair_from_text(raw_message or "")
            objective = partial.objective
            if peer_a and peer_b:
                # Explicit A-vs-B: drop stale Memory/partial objective
                objective = None
            return IntentUnderstandingResult(
                type="competitive_analysis",
                company=company,
                competitors=competitors,
                product=product,
                objective=objective,
                confidence=partial.confidence,
                missing_fields=missing,
                needs_clarification=bool(missing),
                clarification_question=(
                    "请告诉我主要对比哪些竞品？"
                    if missing == ["competitors"]
                    else (
                        "请告诉我要分析的具体产品或市场是什么？"
                        if missing == ["product"]
                        else ("请补充缺失的信息以便开始分析。" if missing else None)
                    )
                ),
                raw_message=raw_message,
            )

        names = _extract_companies_in_order(raw_message)
        company, competitors, product = _resolve_peer_comparison(
            None, names, _infer_product(raw_message), raw_message,
        )
        company, product = _normalize_intel_entities(raw_message, company, product)
        if _is_placeholder_entity(company) or is_invalid_company_entity(company):
            company = None
        competitors = _sanitize_competitors(competitors, company)
        intel = _is_intelligence_collection(raw_message)
        has_analysis = detect_analysis_intent(raw_message)

        # Unknown brands + analysis ask must clarify, never silent out_of_scope
        if not competitors and not company and not intel and not has_analysis:
            return IntentUnderstandingResult(
                type="unsupported",
                confidence=0.3,
                raw_message=raw_message,
            )

        missing = []
        if not company:
            missing.append("company")
        if (
            not intel
            and not competitors
            and not looks_like_competitor_listing_query(raw_message)
        ):
            missing.append("competitors")
        if not product:
            product = infer_default_product(company)
        if not product:
            missing.append("product")

        return IntentUnderstandingResult(
            type="competitive_analysis",
            company=company,
            competitors=competitors,
            product=product,
            objective="intelligence_collection" if intel else None,
            confidence=0.55 if (company or competitors) else 0.35,
            missing_fields=missing,
            needs_clarification=bool(missing),
            clarification_question=(
                "请告诉我主要对比哪些竞品？"
                if missing == ["competitors"]
                else (
                    "请告诉我要分析的具体产品或市场是什么？"
                    if missing == ["product"]
                    else ("请补充缺失的信息以便开始分析。" if missing else None)
                )
            ),
            raw_message=raw_message,
        )
