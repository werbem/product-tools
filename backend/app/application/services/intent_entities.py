"""Shared entity sanitization / peer suggestions for intent + launch mapping."""

from __future__ import annotations

import re
from typing import Any

_PLACEHOLDER_ENTITY_RE = re.compile(
    r"^(?:竞品(?:公司)?|竞争对手|对手|友商|主要竞品|其他竞品|对方|同行|"
    r"竞品公司的竞品分析报告|对比分析报告)$"
)
_NOISE_ENTITY_RE = re.compile(
    r"帮我|请告诉|请补充|完成|进行分析|分析报告|对比报告|竞品分析|做分析"
)

# Pronouns / deixis — never treat as company (「它都有哪些竞品」)
_INVALID_COMPANY_RE = re.compile(
    r"^(?:它|他|她|它们|他们|她们|这个|那个|这些|那些|"
    r"该公司|本公司|贵司|对方|你们|我们|咱|大家)$"
)

# 「竞品公司都有哪些 / 有什么竞品 / 常见对手」— Q&A, not deep-analysis launch
_COMPETITOR_LISTING_RE = re.compile(
    r"(?:常见)?竞品(?:公司)?.{0,4}(?:都)?有(?:哪些|什么)|"
    r"有(?:哪些|什么).{0,6}(?:常见)?竞品|"
    r"(?:有|都有)(?:哪些|什么)竞品|"
    r"竞品是谁|对比了哪些竞品|"
    r"(?:帮我)?(?:推荐|列出|找一下|说说).{0,12}竞品|"
    r"which\s+competitors|who\s+are\s+(?:the\s+)?competitors",
    re.IGNORECASE,
)

# Subject before 竞品…有哪些 / 都有哪些竞品 / 有什么竞品
# Prefer「都有哪些竞品」over bare「有哪些」so「抖音都有哪些」≠ company「抖音都」.
_LISTING_SUBJECT_RE = re.compile(
    r"^[\s]*"
    r"([\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9·\.]{1,24}?)"
    r"(?:的)?"
    r"(?:常见)?"
    r"(?:竞品(?:公司)?|(?:外卖|酒店|业务)?(?:竞品(?:公司)?))"
    r".{0,4}(?:都)?有(?:哪些|什么)"
    r"|"
    r"^[\s]*"
    r"([\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9·\.]{1,24}?)"
    r"(?:都)?有(?:哪些|什么)竞品"
    r"|"
    r"^[\s]*"
    r"([\u4e00-\u9fffA-Za-z0-9][\u4e00-\u9fffA-Za-z0-9·\.]{1,24}?)"
    r"有(?:哪些|什么)竞品"
)

# Brand stems / aliases that must never appear as their own competitor
_BRAND_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"抖音", "抖音电商", "抖音外卖", "字节跳动"}),
    frozenset({"快手", "快手电商"}),
    frozenset({"淘宝", "天猫", "阿里巴巴"}),
    frozenset({"京东", "京东外卖"}),
    frozenset({"美团", "美团外卖"}),
    frozenset({"B站", "哔哩哔哩"}),
)


def looks_like_competitor_listing_query(text: str | None) -> bool:
    """User is *asking who competitors are*, not naming peers for a report."""
    if not text or len(text) > 120:
        return False
    return bool(_COMPETITOR_LISTING_RE.search(text))


def extract_listing_subject_company(text: str | None) -> str | None:
    """Subject company from『京东外卖有什么竞品』/『抖音都有哪些竞品』."""
    if not text:
        return None
    # Only use the listing clause — trailing「帮我完成…分析报告」must not pollute subject
    raw = text.strip()
    clause = re.split(r"[？?！!。；;]", raw, maxsplit=1)[0].strip()
    m = _LISTING_SUBJECT_RE.search(clause) or _LISTING_SUBJECT_RE.search(raw)
    if not m:
        return None
    subject = (m.group(1) or m.group(2) or m.group(3) or "").strip(" ，,、的")
    subject = re.sub(r"(?:的)?(?:常见)?竞品(?:公司)?$", "", subject).strip()
    # 「它都有哪些 / 抖音都有哪些」— 都 belongs to 都有, not the brand
    if subject.endswith("都"):
        subject = subject[:-1].strip()
    if not subject or is_invalid_company_entity(subject):
        return None
    return subject


def is_invalid_company_entity(name: str | None) -> bool:
    """True for placeholders, pronouns, or other non-company tokens."""
    text = (name or "").strip().strip("，,、的")
    if not text:
        return True
    if is_placeholder_entity(text):
        return True
    if _INVALID_COMPANY_RE.match(text):
        return True
    # Glued pronoun+都 that somehow survived (它都)
    if text.endswith("都") and _INVALID_COMPANY_RE.match(text[:-1]):
        return True
    return False


def sanitize_company_name(name: str | None) -> str | None:
    """Return company name or None when pronoun/placeholder/noise."""
    text = (name or "").strip().strip("，,、的")
    # Strip glued compare verbs from bad LLM/regex extractions:「对比美团」→「美团」
    text = re.sub(
        r"^(?:请|帮我|麻烦)?(?:完成|做一下|做|进行)?(?:对比|对标|比较|对照)\s*",
        "",
        text,
    ).strip(" ，,、的")
    text = re.sub(r"^(?:对比|对标|比较|对照)", "", text).strip(" ，,、的")
    if not text or is_invalid_company_entity(text):
        return None
    return text


def is_same_brand_entity(a: str | None, b: str | None) -> bool:
    """True when a/b are the same brand (抖音 vs 抖音电商, etc.)."""
    left = (a or "").strip()
    right = (b or "").strip()
    if not left or not right:
        return False
    if left == right:
        return True
    if left.casefold() == right.casefold():
        return True
    for group in _BRAND_ALIAS_GROUPS:
        if left in group and right in group:
            return True
    return False


def is_placeholder_entity(name: str | None) -> bool:
    text = (name or "").strip().strip("，,、的")
    if not text:
        return True
    if _PLACEHOLDER_ENTITY_RE.match(text):
        return True
    if text.startswith("竞品") or "竞品公司" in text:
        return True
    if "竞品分析" in text or text.endswith("报告"):
        return True
    if text in {"公开市场与主要竞品", "主要竞品", "相关竞品"}:
        return True
    if "公开市场" in text and "竞品" in text:
        return True
    if _NOISE_ENTITY_RE.search(text):
        return True
    return False


def sanitize_competitors(competitors: list[str], company: str | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in competitors or []:
        c = str(raw or "").strip().strip("，,、的")
        if not c or is_placeholder_entity(c):
            continue
        if company and is_same_brand_entity(c, company):
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def sanitize_search_keywords(
    keywords: list[str] | None,
    *,
    company: str | None = None,
) -> list[str]:
    """Drop placeholder / noise tokens so collection queries stay on-topic.

    Intelligence collection uses competitor_company=「公开市场与主要竞品」as a
    gate filler — that must never become a Tavily keyword.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in keywords or []:
        text = str(raw or "").strip()
        if not text:
            continue
        # Split multi-token blobs and drop placeholder segments
        parts = [p.strip() for p in re.split(r"[\s、,/|]+", text) if p.strip()]
        kept = [p for p in parts if not is_placeholder_entity(p)]
        if not kept:
            continue
        cleaned = " ".join(kept)
        if company and cleaned == company:
            # keep company alone — still useful
            pass
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
    return out


_COLLECT_PREFIX_RE = re.compile(
    r"^(?:请?帮我)?(?:再)?(?:收集|搜集|调研|整理一下|找一下|查一下)\s*",
)
_COLLECT_SUFFIX_RE = re.compile(r"(?:相关)?(?:信息|资料|情报|内容)$")


def extract_user_request_focus(
    user_query: str | None,
    *,
    company: str | None = None,
    product: str | None = None,
) -> str:
    """Topic remnant from user ask after stripping collect verbs / entity names.

    Example:「帮我收集字节跳动抖音近期产品策略发展信息」→「近期产品策略发展」
    """
    text = (user_query or "").strip()
    if not text:
        return ""
    text = _COLLECT_PREFIX_RE.sub("", text).strip(" ：:，,。！!？?")
    # Longer tokens first so「抖音电商」wins over「抖音」
    for token in sorted(
        [t for t in (company, product) if t],
        key=len,
        reverse=True,
    ):
        text = text.replace(token, " ")
    text = _COLLECT_SUFFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" ：:，,。 ")
    return text


def compose_entity_user_search_query(
    *,
    company: str | None,
    product: str | None,
    user_query: str | None = None,
    objective: str | None = None,
) -> str:
    """Generic web retry / boost query: 公司 + 产品 + 用户要求内容.

    Never hardcodes a topic like「商业发展」— always derived from the user ask.
    """
    company = (company or "").strip()
    product = (product or "").strip()
    if product and is_placeholder_entity(product):
        product = ""
    focus = extract_user_request_focus(user_query, company=company, product=product)
    if not focus:
        focus = extract_user_request_focus(objective, company=company, product=product)
    if not focus and objective and not is_placeholder_entity(objective):
        # Keep a short objective snippet when focus extraction yields nothing
        focus = re.sub(r"\s+", " ", objective).strip()[:40]
    parts = sanitize_search_keywords(
        [company, product, focus],
        company=company or None,
    )
    return " ".join(parts).strip()


# ── Curated peer catalog (no web on hot path) ─────────────────────────
# Each vertical: member brands → default peers (self filtered at resolve).
_CURATED_VERTICALS: tuple[tuple[frozenset[str], list[str], str], ...] = (
    # (members, peer_pool, default_product_label)
    (
        frozenset({"抖音", "快手", "小红书", "B站", "哔哩哔哩", "微信视频号"}),
        ["快手", "小红书", "B站", "微信视频号"],
        "短视频",
    ),
    (
        frozenset({"美团外卖", "饿了么", "京东外卖", "抖音外卖"}),
        ["美团", "饿了么", "京东外卖", "抖音外卖"],
        "外卖",
    ),
    (
        frozenset({"拼多多", "淘宝", "天猫", "京东", "抖音电商", "快手电商"}),
        ["拼多多", "淘宝", "京东", "抖音电商", "天猫"],
        "电商",
    ),
    (
        frozenset({"携程", "飞猪", "去哪儿", "同程旅行"}),
        ["携程", "美团", "飞猪", "同程旅行", "Booking.com"],
        "在线旅游",
    ),
    (
        frozenset({"滴滴", "滴滴出行", "高德打车", "曹操出行", "T3出行"}),
        ["滴滴", "高德打车", "曹操出行", "美团打车"],
        "出行",
    ),
    (
        frozenset({"支付宝", "微信支付", "云闪付"}),
        ["支付宝", "微信支付", "云闪付"],
        "支付",
    ),
    (
        frozenset({"飞书", "钉钉", "企业微信", "腾讯会议"}),
        ["飞书", "钉钉", "企业微信", "腾讯会议"],
        "协同办公",
    ),
    (
        frozenset({"网易云音乐", "QQ音乐", "酷狗音乐", "汽水音乐"}),
        ["网易云音乐", "QQ音乐", "酷狗音乐", "汽水音乐"],
        "音乐",
    ),
    (
        frozenset({"Insta360", "insta360", "影石", "大疆", "DJI", "GoPro"}),
        ["大疆", "GoPro", "影石"],
        "运动相机/全景相机",
    ),
)

# Parent company → flagship product brand for peer lookup
_PARENT_TO_PRODUCT_BRAND: dict[str, str] = {
    "字节跳动": "抖音",
    "字节": "抖音",
}


def _peers_from_pool(subject: str, pool: list[str], *, limit: int = 3) -> list[str]:
    return [x for x in pool if not is_same_brand_entity(x, subject)][:limit]


def _curated_peers_for_subject(subject: str, product: str) -> list[str]:
    """Match one vertical for a brand subject (+ product hints)."""
    c = (subject or "").strip()
    p = (product or "").strip()
    if not c:
        return []

    ecommerce_product = any(
        k in p for k in ("电商", "零售", "购物", "下沉", "跨境电商")
    )
    delivery_product = "外卖" in p or "即时配送" in p
    hotelish = any(k in p for k in ("酒店", "OTA", "住宿", "旅游", "在线旅游"))
    ride_product = any(k in p for k in ("出行", "打车", "网约车"))
    pay_product = "支付" in p
    collab_product = any(k in p for k in ("协同", "办公", "会议"))
    music_product = "音乐" in p
    camera_product = "相机" in p or "全景" in p

    # Brand+product specials (美团+外卖 vs 美团+酒店)
    if c in {"美团外卖"} or (c == "美团" and delivery_product):
        return _peers_from_pool(c, ["饿了么", "京东外卖", "抖音外卖"])
    if c in {"京东外卖"} or (c == "京东" and delivery_product):
        return _peers_from_pool(c, ["美团", "饿了么", "抖音外卖"])
    if c == "美团" and hotelish:
        return _peers_from_pool(c, ["携程", "飞猪", "同程旅行", "Booking.com"])
    if c == "美团" and ride_product:
        return _peers_from_pool(c, ["滴滴", "高德打车", "曹操出行"])
    if c == "美团":
        # Bare 美团 → local-life cross peers (not only OTA)
        return _peers_from_pool(c, ["饿了么", "抖音", "拼多多", "携程"])

    # Content vs ecommerce for 抖音/快手/小红书
    content_members = _CURATED_VERTICALS[0][0]
    if c in content_members and ecommerce_product:
        return _peers_from_pool(c, ["拼多多", "淘宝", "京东", "抖音电商", "天猫"])

    for members, pool, _label in _CURATED_VERTICALS:
        if c in members:
            return _peers_from_pool(c, pool)

    # Product-hint fallbacks when brand not in a vertical
    if delivery_product:
        return _peers_from_pool(c, ["美团", "饿了么", "抖音外卖", "京东外卖"])
    if ecommerce_product:
        return _peers_from_pool(c, ["拼多多", "淘宝", "京东", "抖音电商", "天猫"])
    if hotelish:
        return _peers_from_pool(c, ["携程", "美团", "飞猪", "同程旅行", "Booking.com"])
    if ride_product:
        return _peers_from_pool(c, ["滴滴", "高德打车", "曹操出行", "美团打车"])
    if pay_product:
        return _peers_from_pool(c, ["支付宝", "微信支付", "云闪付"])
    if collab_product:
        return _peers_from_pool(c, ["飞书", "钉钉", "企业微信", "腾讯会议"])
    if music_product:
        return _peers_from_pool(c, ["网易云音乐", "QQ音乐", "酷狗音乐", "汽水音乐"])
    if camera_product:
        return _peers_from_pool(c, ["大疆", "GoPro", "影石"])
    return []


def suggest_default_competitors(company: str | None, product: str | None) -> list[str]:
    """Curated peer suggestions when user asks『常见竞品有哪些』(local, no web)."""
    c = (company or "").strip()
    p = (product or "").strip()
    if not c:
        return []

    peers = _curated_peers_for_subject(c, p)
    if peers:
        return peers

    # Parent company → flagship product brand (字节跳动 + 抖音 → 抖音 peers)
    brand = _PARENT_TO_PRODUCT_BRAND.get(c)
    if brand:
        peers = _curated_peers_for_subject(brand, p or brand)
        if peers:
            return peers

    # Product itself is a known brand (company=字节跳动, product=抖音)
    if p and p != c and not is_placeholder_entity(p):
        peers = _curated_peers_for_subject(p, p)
        if peers:
            return peers
    return []


def infer_default_product(company: str | None, product: str | None = None) -> str | None:
    """Default product/market when company is a known brand but product is unset."""
    if product:
        return product
    c = (company or "").strip()
    if not c:
        return None
    if c in _PARENT_TO_PRODUCT_BRAND:
        return _PARENT_TO_PRODUCT_BRAND[c]
    if c == "美团":
        return "本地生活"
    for members, _pool, label in _CURATED_VERTICALS:
        if c in members:
            return label
    return None


def resolve_competitor_suggestions(
    company: str | None,
    product: str | None,
    memory: Any | None = None,
    *,
    intent_competitors: list[str] | None = None,
) -> dict[str, Any]:
    """Memory/edges ∪ curated peers for listing answers (no web).

    Priority: memory → intent → curated. Persist curated hits via MemoryWriter
    on listing so the next ask in the same project is a Memory hit.
    """
    from app.domain.entities.project_memory import ProjectMemory, lookup_peers

    company = (company or "").strip() or None
    product = (product or "").strip() or None
    if product and company and is_same_brand_entity(product, company):
        product = infer_default_product(company) or product
    mem_obj: ProjectMemory | None = memory if isinstance(memory, ProjectMemory) else None

    intent_peers = sanitize_competitors(list(intent_competitors or []), company)
    memory_peers = sanitize_competitors(
        lookup_peers(mem_obj, company, product) if mem_obj else [],
        company,
    )
    curated_peers = suggest_default_competitors(company, product)

    peers: list[str] = []
    sources: list[str] = []
    seen: set[str] = set()

    def _extend(names: list[str], tag: str) -> None:
        for name in names:
            if is_same_brand_entity(name, company):
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            peers.append(name)
            sources.append(tag)

    _extend(memory_peers, "memory")
    _extend(intent_peers, "intent")
    _extend(curated_peers, "curated")
    peers = peers[:4]
    sources = sources[: len(peers)]

    has_mem = "memory" in sources
    has_cur = "curated" in sources
    has_int = "intent" in sources
    if has_mem and (has_cur or has_int):
        mode = "mixed_peers"
    elif has_mem:
        mode = "memory_peers"
    elif has_cur:
        mode = "curated_peers"
    elif has_int:
        mode = "intent_peers"
    else:
        mode = "empty"

    return {
        "peers": peers,
        "sources": sources,
        "question_mode": mode,
        "memory_peers": [n for n, s in zip(peers, sources) if s == "memory"],
        "curated_peers": [n for n, s in zip(peers, sources) if s == "curated"],
        "intent_peers": [n for n, s in zip(peers, sources) if s == "intent"],
    }
