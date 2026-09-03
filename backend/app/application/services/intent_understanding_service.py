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
from app.infrastructure.agents.intent_prompt import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE
from app.infrastructure.llm.client import LLMClient, llm_client

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
_KNOWN_COMPANIES = (
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
)

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
    hits.sort(key=lambda x: x[0])
    seen: set[str] = set()
    ordered: list[str] = []
    for _, name in hits:
        if name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _infer_product(text: str) -> str | None:
    for pattern, label in _PRODUCT_HINTS:
        if re.search(pattern, text):
            return label
    return None


def _resolve_peer_comparison(
    company: str | None,
    competitors: list[str],
    product: str | None,
    raw_message: str,
) -> tuple[str | None, list[str], str | None]:
    """Fill company/competitors/product for peer A-vs-B queries."""
    names = _extract_companies_in_order(raw_message)
    comps = list(competitors)

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

        try:
            llm_output = await self._call_llm(merged_message, partial)
            return self._build_result(llm_output, request.message, partial)
        except asyncio.TimeoutError:
            logger.warning(
                "intent_timeout conversation_id=%s timeout_s=%s",
                request.conversation_id,
                _intent_llm_timeout_s(),
            )
            # Conservative rule/heuristic only — never invent a silent Deep launch path.
            return self._heuristic_result(request.message, partial)
        except Exception as exc:
            logger.warning(
                "intent_fallback conversation_id=%s err=%s",
                request.conversation_id,
                f"{type(exc).__name__}: {exc}",
            )
            return self._heuristic_result(request.message, partial)

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
        company, product = _normalize_intel_entities(raw_message, company, product)

        if intel:
            competitors = [
                c for c in competitors
                if c and c not in {company, product}
            ]

        missing: list[str] = []
        if not company:
            missing.append("company")
        if not intel and not competitors:
            missing.append("competitors")
        if not product:
            missing.append("product")

        needs_clarification = bool(missing)
        clarification = None
        if needs_clarification:
            if "company" in missing and "competitors" in missing:
                clarification = "请告诉我要对比的双方公司，例如：分析拼多多与淘宝的差异。"
            elif "company" in missing:
                clarification = "请告诉我您要分析哪家公司（我方公司）？"
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
            intel = _is_intelligence_collection(raw_message)
            missing: list[str] = []
            if not company:
                missing.append("company")
            if not intel and not competitors:
                missing.append("competitors")
            if not product:
                missing.append("product")
            return IntentUnderstandingResult(
                type="competitive_analysis",
                company=company,
                competitors=competitors,
                product=product,
                objective=partial.objective,
                confidence=partial.confidence,
                missing_fields=missing,
                needs_clarification=bool(missing),
                clarification_question=(
                    "请补充缺失的信息以便开始分析。" if missing else None
                ),
                raw_message=raw_message,
            )

        names = _extract_companies_in_order(raw_message)
        company, competitors, product = _resolve_peer_comparison(
            None, names, _infer_product(raw_message), raw_message,
        )
        company, product = _normalize_intel_entities(raw_message, company, product)
        intel = _is_intelligence_collection(raw_message)

        if not competitors and not company and not intel:
            return IntentUnderstandingResult(
                type="unsupported",
                confidence=0.3,
                raw_message=raw_message,
            )

        missing = []
        if not company:
            missing.append("company")
        if not intel and not competitors:
            missing.append("competitors")
        if not product:
            missing.append("product")

        return IntentUnderstandingResult(
            type="competitive_analysis",
            company=company,
            competitors=competitors,
            product=product,
            objective="intelligence_collection" if intel else None,
            confidence=0.5,
            missing_fields=missing,
            needs_clarification=bool(missing),
            clarification_question="请补充缺失的信息以便开始分析。" if missing else None,
            raw_message=raw_message,
        )
