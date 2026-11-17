"""Evidence Reuse V1 — Step 1 judgment layer (no Research integration).

Given a current Deep task context and historical completed tasks, decide which
evidence items are safe to reuse and which entities/dimensions remain as gaps.

Does not call Search, Planner, Memory, or ResearchAgent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

from app.infrastructure.agents.planner_agent import _DIMENSION_ZH_MAP, normalize_dimension
from app.infrastructure.tools.evidence_freshness import evidence_cutoff_date

# Minimal alias groups for known brand variants (not a full entity KB).
_ENTITY_ALIAS_GROUPS: tuple[frozenset[str], ...] = (
    frozenset({"滴滴", "滴滴出行", "滴滴打车"}),
)

_PLACEHOLDER_COMPETITORS = frozenset(
    {
        "公开市场与主要竞品",
        "公开市场",
        "主要竞品",
        "竞品",
        "待确认",
        "未知",
        "n/a",
        "na",
        "none",
    },
)


@dataclass(frozen=True)
class CurrentReuseRequest:
    """Inputs for one reuse evaluation (caller-built; no Memory)."""

    project_id: str
    our_company: str
    competitors: Sequence[str] = field(default_factory=list)
    analysis_scope: Sequence[str] = field(default_factory=list)
    workflow_kind: str | None = None
    evidence_max_age_months: int = 48
    max_undated_evidence_items: int = 5
    # Optional: exclude the in-flight task id from historical scan
    current_task_id: str | None = None


@dataclass
class EvidenceReuseResult:
    reusable_evidence: list[dict[str, Any]]
    gap_entities: list[str]
    gap_dimensions: list[str]
    sufficient: bool
    reuse_meta: dict[str, Any]
    reuse_disabled: bool = False
    reuse_disabled_reason: str | None = None


def normalize_entity_name(name: str | None) -> str:
    """Canonicalize a company/competitor label for set comparison."""
    raw = (name or "").strip()
    if not raw:
        return ""
    for group in _ENTITY_ALIAS_GROUPS:
        if raw in group:
            # Stable canonical: shortest then lexicographic among aliases
            return sorted(group, key=lambda s: (len(s), s))[0]
    return raw.casefold()


def entity_alias_forms(name: str | None) -> frozenset[str]:
    """Surface forms used for conservative text hit detection."""
    raw = (name or "").strip()
    if not raw:
        return frozenset()
    for group in _ENTITY_ALIAS_GROUPS:
        if raw in group or normalize_entity_name(raw) in {normalize_entity_name(x) for x in group}:
            return frozenset(group)
    return frozenset({raw})


def competitor_combination_key(
    our_company: str,
    competitors: Sequence[str] | None,
) -> tuple[str, frozenset[str]]:
    """Normalized (our, competitor-set) — order-insensitive competitors."""
    our = normalize_entity_name(our_company)
    comps: set[str] = set()
    for raw in competitors or []:
        c = (raw or "").strip()
        if not c or _is_placeholder_competitor(c):
            continue
        cn = normalize_entity_name(c)
        if cn and cn != our:
            comps.add(cn)
    return our, frozenset(comps)


def _is_placeholder_competitor(name: str) -> bool:
    key = (name or "").strip().casefold()
    return key in {p.casefold() for p in _PLACEHOLDER_COMPETITORS}


def is_deep_workflow(workflow_kind: str | None) -> bool:
    wk = (workflow_kind or "").strip().casefold()
    if wk == "intelligence_collection":
        return False
    # Missing / deep_analysis / empty → Deep (historical Deep often omits entry.workflow_kind)
    return True


def resolve_workflow_kind(entry: Mapping[str, Any]) -> str | None:
    """Prefer entry.workflow_kind; fall back to user_input.optional.workflow_kind."""
    raw = entry.get("workflow_kind")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    state = entry.get("state") if isinstance(entry.get("state"), dict) else {}
    user_input = state.get("user_input") if isinstance(state.get("user_input"), dict) else {}
    optional = user_input.get("optional") if isinstance(user_input.get("optional"), dict) else {}
    opt_wk = optional.get("workflow_kind")
    if isinstance(opt_wk, str) and opt_wk.strip():
        return opt_wk.strip()
    return None


def extract_task_entities(entry: Mapping[str, Any]) -> tuple[str, list[str]]:
    """Read our_company + competitors from a persisted task entry."""
    state = entry.get("state") if isinstance(entry.get("state"), dict) else {}
    user_input = state.get("user_input") if isinstance(state.get("user_input"), dict) else {}
    validated = state.get("validated_input") if isinstance(state.get("validated_input"), dict) else {}
    optional = user_input.get("optional") if isinstance(user_input.get("optional"), dict) else {}

    our = str(
        validated.get("our_company")
        or user_input.get("our_company")
        or "",
    ).strip()

    competitors: list[str] = []
    raw_comps = optional.get("competitors")
    if isinstance(raw_comps, list):
        competitors = [str(c).strip() for c in raw_comps if str(c or "").strip()]

    if not competitors:
        # Fall back to competitor_company when list missing (join with 、/,)
        comp_field = str(
            validated.get("competitor_company")
            or user_input.get("competitor_company")
            or "",
        ).strip()
        if comp_field and not _is_placeholder_competitor(comp_field):
            for part in _split_competitor_field(comp_field):
                if part and not _is_placeholder_competitor(part):
                    competitors.append(part)

    return our, competitors


def _split_competitor_field(text: str) -> list[str]:
    parts: list[str] = []
    buf = text
    for sep in ("、", ",", "/", "|", ";"):
        buf = buf.replace(sep, "、")
    for p in buf.split("、"):
        p = p.strip()
        if p:
            parts.append(p)
    return parts


def scope_to_canonical_zh(scope_item: str) -> str | None:
    """Map an analysis_scope entry to canonical Chinese dimension, or None if unknown."""
    raw = (scope_item or "").strip()
    if not raw:
        return None
    # English category-style → Chinese via existing map
    zh = normalize_dimension(raw)
    if zh != raw or raw.casefold() in {k.casefold() for k in _DIMENSION_ZH_MAP}:
        return zh if zh else None
    # Already Chinese: accept if it equals any mapped Chinese value or is unchanged non-empty
    known_zh = set(_DIMENSION_ZH_MAP.values())
    if raw in known_zh:
        return raw
    # Unmapped free-text Chinese scope — conservative: no coverage credit
    # unless normalize_dimension found an English substring match (zh may change)
    if zh != raw:
        return zh
    return None


def category_to_canonical_zh(category: str) -> str | None:
    """Map Evidence.category (usually English) to canonical Chinese dimension."""
    raw = (category or "").strip()
    if not raw:
        return None
    # competitive_landscape etc.: normalize_dimension handles substring "competitive"
    zh = normalize_dimension(raw)
    if not zh:
        return None
    # If still looks like unknown English with no map hit, reject
    known_zh = set(_DIMENSION_ZH_MAP.values())
    if zh in known_zh:
        return zh
    if zh != raw and any(eng in raw.casefold() for eng in _DIMENSION_ZH_MAP):
        return zh
    # category already Chinese and known
    if raw in known_zh:
        return raw
    return None


def evidence_matches_scope(category: str, analysis_scope: Sequence[str]) -> bool:
    cat_zh = category_to_canonical_zh(category)
    if not cat_zh:
        return False
    for scope in analysis_scope:
        scope_zh = scope_to_canonical_zh(scope)
        if scope_zh and scope_zh == cat_zh:
            return True
    return False


def evidence_hits_entity(item: Mapping[str, Any], entity_name: str) -> bool:
    """Conservative text hit: any alias of entity appears in title/content/source."""
    aliases = entity_alias_forms(entity_name)
    if not aliases:
        return False
    blob = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("content") or ""),
            str(item.get("source") or ""),
        ],
    )
    if not blob.strip():
        return False
    # Prefer longer aliases first to avoid accidental short hits when possible
    for alias in sorted(aliases, key=len, reverse=True):
        if alias and alias in blob:
            return True
    return False


def evidence_hits_any_entity(item: Mapping[str, Any], entities: Sequence[str]) -> bool:
    return any(evidence_hits_entity(item, e) for e in entities if (e or "").strip())


def is_fresh_evidence(
    item: Mapping[str, Any],
    *,
    max_age_months: int = 48,
    today: date | None = None,
) -> bool:
    """True if dated item is in-window; undated deferred to caller quota."""
    cutoff = evidence_cutoff_date(max_age_months, today=today)
    parsed = _parse_evidence_date(item)
    if parsed is not None:
        return parsed >= cutoff
    # Undated: not expired by date; eligibility uses undated quota in evaluate()
    return True


def is_dated_expired(
    item: Mapping[str, Any],
    *,
    max_age_months: int = 48,
    today: date | None = None,
) -> bool:
    parsed = _parse_evidence_date(item)
    if parsed is None:
        return False
    return parsed < evidence_cutoff_date(max_age_months, today=today)


def _parse_evidence_date(item: Mapping[str, Any]) -> date | None:
    raw = str(item.get("date") or "").strip()
    if raw:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    return None


def has_valid_url(item: Mapping[str, Any]) -> bool:
    url = str(item.get("url") or "").strip()
    return url.startswith(("http://", "https://"))


def merge_and_renumber_evidence(
    seed: Sequence[Mapping[str, Any]],
    new_items: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """URL-dedupe then assign E001, E002, ... (pure helper; not wired to Research)."""
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for src in list(seed) + list(new_items or []):
        if not isinstance(src, Mapping):
            continue
        url = str(src.get("url") or "").strip()
        if url:
            if url in seen:
                continue
            seen.add(url)
        item = dict(src)
        merged.append(item)
    for idx, item in enumerate(merged):
        item["id"] = f"E{idx + 1:03d}"
    return merged


def load_tasks_snapshot(
    tasks: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Mapping[str, Any]]:
    """Thin adapter: use injected map or task_report_runtime.get_tasks()."""
    if tasks is not None:
        return dict(tasks)
    from app.infrastructure.persistence import task_report_runtime

    return dict(task_report_runtime.get_tasks())


class EvidenceReuseService:
    """Pure judgment service for Evidence Reuse V1 Step 1."""

    def evaluate(
        self,
        current: CurrentReuseRequest,
        historical_tasks: Mapping[str, Mapping[str, Any]] | None = None,
        *,
        today: date | None = None,
    ) -> EvidenceReuseResult:
        today = today or date.today()
        meta_base: dict[str, Any] = {
            "reused_count": 0,
            "candidate_count": 0,
            "gap_entities": [],
            "gap_dimensions": [],
            "sufficient": False,
        }

        if not is_deep_workflow(current.workflow_kind):
            return EvidenceReuseResult(
                reusable_evidence=[],
                gap_entities=list(self._required_entities(current)),
                gap_dimensions=list(self._required_dimensions(current)),
                sufficient=False,
                reuse_meta={
                    **meta_base,
                    "gap_entities": list(self._required_entities(current)),
                    "gap_dimensions": list(self._required_dimensions(current)),
                    "reuse_disabled": True,
                    "reuse_disabled_reason": "intelligence_collection",
                },
                reuse_disabled=True,
                reuse_disabled_reason="intelligence_collection",
            )

        tasks = load_tasks_snapshot(historical_tasks)
        current_combo = competitor_combination_key(current.our_company, current.competitors)
        required_entities = self._required_entities(current)
        required_dimensions = self._required_dimensions(current)

        # Unmapped scopes are immediate gaps (conservative)
        gap_dimensions = [
            s for s in (current.analysis_scope or [])
            if (s or "").strip() and scope_to_canonical_zh(s) is None
        ]
        mapped_required_zh = [
            zh for zh in (
                scope_to_canonical_zh(s) for s in (current.analysis_scope or [])
            )
            if zh
        ]

        candidates: list[dict[str, Any]] = []
        undated_kept = 0
        max_undated = max(0, int(current.max_undated_evidence_items))

        for task_id, entry in tasks.items():
            if not isinstance(entry, Mapping):
                continue
            if current.current_task_id and str(task_id) == str(current.current_task_id):
                continue
            if str(entry.get("status") or "").lower() != "completed":
                continue
            if str(entry.get("project_id") or "") != str(current.project_id):
                continue

            hist_wk = resolve_workflow_kind(entry)
            if not is_deep_workflow(hist_wk):
                continue

            hist_our, hist_comps = extract_task_entities(entry)
            if competitor_combination_key(hist_our, hist_comps) != current_combo:
                continue

            state = entry.get("state") if isinstance(entry.get("state"), dict) else {}
            bundle = state.get("evidence_bundle") if isinstance(state.get("evidence_bundle"), dict) else {}
            items = bundle.get("evidence_items") if isinstance(bundle.get("evidence_items"), list) else []

            for raw in items:
                if not isinstance(raw, Mapping):
                    continue
                item = dict(raw)
                if not has_valid_url(item):
                    continue
                if is_dated_expired(
                    item,
                    max_age_months=current.evidence_max_age_months,
                    today=today,
                ):
                    continue
                if _parse_evidence_date(item) is None:
                    # undated: allow under same cap as research freshness
                    if undated_kept >= max_undated:
                        continue
                if not evidence_hits_any_entity(item, required_entities):
                    continue
                if mapped_required_zh and not evidence_matches_scope(
                    str(item.get("category") or ""),
                    current.analysis_scope,
                ):
                    continue
                # If no mappable scopes at all, do not accept category-based items
                if not mapped_required_zh:
                    continue

                if _parse_evidence_date(item) is None:
                    undated_kept += 1

                item["_reuse_source_task_id"] = str(entry.get("task_id") or task_id)
                candidates.append(item)

        # URL dedupe among candidates (keep first)
        reusable = merge_and_renumber_evidence(candidates, [])
        # merge_and_renumber assigns E ids — fine for inspection; Step 2 may re-merge with new

        # Coverage
        entity_covered = {
            e: any(evidence_hits_entity(it, e) for it in reusable)
            for e in required_entities
        }
        gap_entities = [e for e, ok in entity_covered.items() if not ok]

        dim_covered_zh: set[str] = set()
        for it in reusable:
            zh = category_to_canonical_zh(str(it.get("category") or ""))
            if zh:
                dim_covered_zh.add(zh)

        for scope in current.analysis_scope or []:
            scope_zh = scope_to_canonical_zh(scope)
            if scope_zh is None:
                if (scope or "").strip() and scope not in gap_dimensions:
                    gap_dimensions.append(scope)
                continue
            if scope_zh not in dim_covered_zh and scope not in gap_dimensions:
                gap_dimensions.append(scope)

        sufficient = not gap_entities and not gap_dimensions and bool(reusable)

        # Edge: no required entities / scopes → not sufficient without evidence
        if not required_entities or not mapped_required_zh:
            sufficient = False

        reuse_meta = {
            "reused_count": len(reusable),
            "candidate_count": len(candidates),
            "gap_entities": list(gap_entities),
            "gap_dimensions": list(gap_dimensions),
            "sufficient": sufficient,
            "reuse_disabled": False,
        }

        return EvidenceReuseResult(
            reusable_evidence=reusable,
            gap_entities=gap_entities,
            gap_dimensions=gap_dimensions,
            sufficient=sufficient,
            reuse_meta=reuse_meta,
            reuse_disabled=False,
        )

    @staticmethod
    def _required_entities(current: CurrentReuseRequest) -> list[str]:
        our = (current.our_company or "").strip()
        out: list[str] = []
        if our:
            out.append(our)
        seen = {normalize_entity_name(our)} if our else set()
        for c in current.competitors or []:
            c = (c or "").strip()
            if not c or _is_placeholder_competitor(c):
                continue
            key = normalize_entity_name(c)
            if key in seen:
                continue
            seen.add(key)
            out.append(c)
        return out

    @staticmethod
    def _required_dimensions(current: CurrentReuseRequest) -> list[str]:
        return [s for s in (current.analysis_scope or []) if (s or "").strip()]
