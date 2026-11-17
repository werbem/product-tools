"""Decision Entity extraction — provenance-aware facade (Phase 3).

Wraps ``intent_entities`` + Memory/prior fallbacks into ``DecisionEntities``.
Never selects workflow and never launches Deep / Research.
Not wired into ConversationService production path in Phase 3.
"""

from __future__ import annotations

import re
from typing import Any

from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import (
    DecisionEntities,
    EntitySlot,
    EntitySource,
)
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.application.services.intent_entities import (
    extract_listing_subject_company,
    infer_default_product,
    is_invalid_company_entity,
    looks_like_competitor_listing_query,
    resolve_competitor_suggestions,
    sanitize_company_name,
    sanitize_competitors,
    suggest_default_competitors,
)

_TIME_RANGE_RE = re.compile(
    r"(?:近(?:一|两|1|2)?(?:周|个月|月|年)|最近|近期|本周|本月|今年|去年|"
    r"过去\s*\d+\s*(?:天|日|周|个月|月|年)|"
    r"last\s+\d+\s+(?:days?|weeks?|months?|years?)|"
    r"recent(?:ly)?|this\s+(?:week|month|year))",
    re.IGNORECASE,
)

_VS_PAIR_RE = re.compile(
    r"(?:对比|分析|比较)?\s*"
    r"([\u4e00-\u9fffA-Za-z0-9·\.]{2,20})"
    r"\s*(?:和|与|vs\.?|VS|VS\.|/)\s*"
    r"([\u4e00-\u9fffA-Za-z0-9·\.]{2,20})",
)


def _str_slot(
    value: str | None,
    source: EntitySource,
    confidence: float,
) -> EntitySlot:
    text = sanitize_company_name(value)
    if not text:
        return EntitySlot(value=None, source="unknown", confidence=0.0)
    return EntitySlot(value=text, source=source, confidence=confidence)


def _product_slot(
    value: str | None,
    source: EntitySource,
    confidence: float,
) -> EntitySlot:
    text = (value or "").strip() or None
    if not text:
        return EntitySlot(value=None, source="unknown", confidence=0.0)
    if is_invalid_company_entity(text) and len(text) <= 2:
        return EntitySlot(value=None, source="unknown", confidence=0.0)
    return EntitySlot(value=text, source=source, confidence=confidence)


def _extract_time_range(message: str) -> EntitySlot:
    m = _TIME_RANGE_RE.search(message or "")
    if not m:
        return EntitySlot(value=None, source="unknown", confidence=0.0)
    return EntitySlot(value=m.group(0).strip(), source="message", confidence=0.75)


def _extract_vs_pair(message: str) -> tuple[str | None, str | None]:
    m = _VS_PAIR_RE.search(message or "")
    if not m:
        return None, None
    return sanitize_company_name(m.group(1)), sanitize_company_name(m.group(2))


def _memory_fields(memory: Any | None) -> tuple[str | None, str | None, list[str]]:
    if memory is None:
        return None, None, []
    ents = getattr(memory, "entities", None)
    if ents is None and isinstance(memory, dict):
        ents = memory.get("entities") or memory
    if ents is None:
        return None, None, []
    if isinstance(ents, dict):
        company = sanitize_company_name(ents.get("our_company") or ents.get("company"))
        product = (ents.get("product") or None)
        comps = list(ents.get("competitors") or [])
    else:
        company = sanitize_company_name(getattr(ents, "our_company", None))
        product = getattr(ents, "product", None)
        comps = list(getattr(ents, "competitors", None) or [])
    product = (str(product).strip() if product else None) or None
    comps = sanitize_competitors(comps, company)
    return company, product, comps


class DecisionEntityExtractor:
    """Build DecisionEntities with explicit sources. No workflow side effects."""

    def extract(
        self,
        message: str,
        *,
        legacy_intent: IntentUnderstandingResult | None = None,
        context: DecisionContext | None = None,
        memory: Any | None = None,
        prior_company: str | None = None,
        prior_product: str | None = None,
        prior_competitors: list[str] | None = None,
        fill_curated_competitors: bool = True,
    ) -> DecisionEntities:
        text = (message or "").strip()
        if not text:
            raise ValueError("message must not be empty")

        ctx = context
        mem_company, mem_product, mem_comps = _memory_fields(memory)
        if ctx is not None:
            mem_company = sanitize_company_name(ctx.memory_company) or mem_company
            mem_product = (ctx.memory_product or mem_product)
            if ctx.memory_competitors:
                mem_comps = sanitize_competitors(
                    list(ctx.memory_competitors) + mem_comps,
                    mem_company,
                )

        prior_company_s = sanitize_company_name(prior_company)
        prior_product_s = (prior_product or "").strip() or None
        prior_comps = sanitize_competitors(list(prior_competitors or []), prior_company_s)

        seed_company = sanitize_company_name(
            legacy_intent.company if legacy_intent else None,
        )
        seed_product = (
            (legacy_intent.product or "").strip() if legacy_intent else None
        ) or None
        seed_comps = sanitize_competitors(
            list(legacy_intent.competitors or []) if legacy_intent else [],
            seed_company,
        )

        listing_subject = extract_listing_subject_company(text)
        vs_a, vs_b = _extract_vs_pair(text)

        if listing_subject:
            company_slot = EntitySlot(
                value=listing_subject, source="message", confidence=0.9,
            )
        elif vs_a:
            company_slot = EntitySlot(value=vs_a, source="message", confidence=0.88)
        elif seed_company:
            company_slot = EntitySlot(
                value=seed_company, source="message", confidence=0.85,
            )
        elif prior_company_s:
            company_slot = EntitySlot(
                value=prior_company_s, source="prior", confidence=0.8,
            )
        elif mem_company:
            company_slot = EntitySlot(
                value=mem_company, source="memory", confidence=0.75,
            )
        else:
            company_slot = EntitySlot(value=None, source="unknown", confidence=0.0)

        # 「它都有哪些竞品」→ subject None; resolve from prior/memory
        if (
            looks_like_competitor_listing_query(text)
            and listing_subject is None
            and not company_slot.value
        ):
            if prior_company_s:
                company_slot = EntitySlot(
                    value=prior_company_s, source="prior", confidence=0.82,
                )
            elif mem_company:
                company_slot = EntitySlot(
                    value=mem_company, source="memory", confidence=0.78,
                )

        company_name = (
            company_slot.value if isinstance(company_slot.value, str) else None
        )

        if seed_product:
            product_slot = _product_slot(seed_product, "message", 0.85)
        elif prior_product_s:
            product_slot = _product_slot(prior_product_s, "prior", 0.8)
        elif mem_product:
            product_slot = _product_slot(mem_product, "memory", 0.75)
        else:
            inferred = infer_default_product(company_name)
            product_slot = (
                _product_slot(inferred, "inferred", 0.55)
                if inferred
                else _product_slot(None, "unknown", 0.0)
            )

        product_name = (
            product_slot.value if isinstance(product_slot.value, str) else None
        )

        comps: list[str] = []
        comp_source: EntitySource = "unknown"
        conf = 0.0

        if vs_b:
            comps = sanitize_competitors([vs_b] + seed_comps, company_name)
            comp_source = "message"
            conf = 0.88
        elif seed_comps:
            comps = sanitize_competitors(seed_comps, company_name)
            comp_source = "message"
            conf = 0.85
        elif prior_comps:
            comps = sanitize_competitors(prior_comps, company_name)
            comp_source = "prior"
            conf = 0.8
        elif mem_comps:
            comps = sanitize_competitors(mem_comps, company_name)
            comp_source = "memory"
            conf = 0.75

        if fill_curated_competitors and not comps and company_name:
            pack = resolve_competitor_suggestions(
                company_name,
                product_name,
                memory,
                intent_competitors=seed_comps or None,
            )
            peers = list(pack.get("peers") or [])
            sources = list(pack.get("sources") or [])
            if peers:
                comps = peers
                if "memory" in sources and "curated" not in sources:
                    comp_source = "memory"
                    conf = 0.75
                else:
                    comp_source = "curated"
                    conf = 0.7
            else:
                curated = suggest_default_competitors(company_name, product_name)[:4]
                if curated:
                    comps = curated
                    comp_source = "curated"
                    conf = 0.65

        competitors_slot = EntitySlot(
            value=comps,
            source=comp_source if comps else "unknown",
            confidence=conf if comps else 0.0,
        )

        missing: list[str] = []
        if not company_name:
            missing.append("company")
        if not product_name:
            missing.append("product")
        if not comps:
            missing.append("competitors")

        return DecisionEntities(
            company=company_slot,
            product=product_slot,
            competitors=competitors_slot,
            time_range=_extract_time_range(text),
            missing_slots=missing,
        )


def entities_imply_launch(_entities: DecisionEntities) -> bool:
    """Phase 3 invariant: entities never imply workflow launch."""
    return False
