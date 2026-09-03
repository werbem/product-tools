"""Compare Agent — LLM-powered evidence-backed gap analysis."""

from __future__ import annotations

import json

from app.application.dto.agent_dto import (
    CompareInput, CompareOutput, FeatureItem, GapAnalysis, GapItem,
)
from app.config.constants import Phase
from app.infrastructure.agents.base import AgentContext, AgentResult, BaseAgent
from app.infrastructure.agents.compare_prompt import (
    SYSTEM_PROMPT, build_compare_prompt, build_cluster_compare_prompt,
)
from app.infrastructure.llm.client import llm_client

def _dget(obj, key, default=None):
    """Safe dict/object access — handles both Pydantic models and plain dicts."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


# Compare input cap — aligned with full mode max_evidence_items budget (15 → top 12 for LLM)
COMPARE_EVIDENCE_INPUT_CAP = 12
_TEMPORAL_PRIORITY: dict[str, float] = {
    "recent": 0.0,
    "aging": 1.0,
    "mixed": 1.5,
    "unknown": 2.0,
    "stale": 3.0,
    "historical": 4.0,
}
_CONFIDENCE_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2, "estimated": 3}


def _get_temporal_level(item) -> str:
    """Read temporal_level from quality_score (dict or object)."""
    qs = _dget(item, "quality_score", None) or {}
    if isinstance(qs, dict):
        return qs.get("temporal_level", "") or ""
    return getattr(qs, "temporal_level", "") or ""


def _evidence_sort_key(item) -> tuple[float, int]:
    """Sort evidence by temporal priority then confidence rank."""
    level = _get_temporal_level(item) or "unknown"
    confidence = _dget(item, "confidence", "estimated")
    return (
        _TEMPORAL_PRIORITY.get(level, 2.0),
        _CONFIDENCE_RANK.get(confidence, 3),
    )


def _aggregate_temporal_levels(levels: list[str]) -> str:
    """Aggregate temporal levels via 70% dominance rule."""
    tiers = ["recent", "aging", "stale", "historical", "unknown"]
    dist = {t: 0 for t in tiers}
    for lvl in levels:
        if lvl not in dist:
            lvl = "unknown"
        dist[lvl] += 1
    total = sum(dist.values())
    if total == 0:
        return "unknown"
    for t in tiers:
        if dist[t] / total >= 0.70:
            return t
    return "mixed"


class CompareAgent(BaseAgent[CompareInput, CompareOutput]):

    def __init__(self) -> None:
        self._partial_input: CompareInput | None = None
        self._partial_raw_text: str = ""

    @property
    def agent_name(self) -> str:
        return "compare"

    @property
    def phase(self) -> Phase:
        return Phase.COMPARING

    def build_partial_result(self) -> AgentResult:
        """Timeout fallback: parse partial LLM JSON, else evidence stub."""
        from app.infrastructure.agents.timeout_stubs import (
            build_compare_stub_from_evidence,
            try_parse_compare_llm_json,
        )

        input_data = self._partial_input
        our = getattr(input_data, "our_company", "") if input_data else ""
        comp = getattr(input_data, "competitor_company", "") if input_data else ""
        product = getattr(input_data, "product", "") if input_data else ""
        eb = getattr(input_data, "evidence_bundle", {}) if input_data else {}
        clusters = list(getattr(input_data, "evidence_clusters", None) or []) if input_data else []
        raw_items = _dget(eb, "evidence_items", []) or []

        parsed = try_parse_compare_llm_json(self._partial_raw_text)
        if parsed and (parsed.differences or parsed.capability_gaps):
            evidence_map, cluster_map = self._build_temporal_maps(raw_items, clusters)
            gap = self._build_gap_analysis(parsed, raw_items, cluster_map, evidence_map)
            gap_dict = gap.model_dump()
            gap_dict.update({
                "compare_timeout": True,
                "compare_partial": True,
                "compare_fallback": "partial_json",
                "generation_note": "对比结果来自超时前的部分 LLM 输出",
            })
            # Store enriched dict on a plain CompareOutput via monkey-patch field
            out = CompareOutput(
                gap_analysis=gap,
                dimensions_analyzed=list(parsed.dimensions_analyzed or []),
                evidence_references_count=len(gap.evidence_references or []),
            )
            return AgentResult(
                success=True,
                output=out,
                phase_record={
                    "phase": Phase.COMPARING.value,
                    "status": "completed",
                    "error": "compare_partial_on_timeout",
                    "compare_timeout": True,
                    "compare_partial": True,
                    "compare_fallback": "partial_json",
                    "gap_dict": gap_dict,
                },
            )

        gap_dict = build_compare_stub_from_evidence(
            eb, our_company=our, competitor_company=comp, product=product,
        )
        # Reconstruct GapAnalysis without meta keys for typed output
        meta_keys = {
            "compare_timeout", "compare_fallback", "generation_note",
            "stub_evidence_count", "compare_partial",
        }
        gap_body = {k: v for k, v in gap_dict.items() if k not in meta_keys}
        gap = GapAnalysis(**{k: gap_body[k] for k in GapAnalysis.model_fields if k in gap_body})
        out = CompareOutput(
            gap_analysis=gap,
            evidence_references_count=len(gap_dict.get("evidence_references") or []),
        )
        return AgentResult(
            success=True,
            output=out,
            phase_record={
                "phase": Phase.COMPARING.value,
                "status": "completed",
                "error": "compare_stub_on_timeout",
                "compare_timeout": True,
                "compare_fallback": "evidence_stub",
                "gap_dict": gap_dict,
            },
        )

    @staticmethod
    def _build_temporal_maps(
        evidence_items: list,
        clusters: list,
    ) -> tuple[dict[str, str], dict[str, str]]:
        """Map evidence/cluster id -> temporal_level for gap resolution."""
        evidence_map: dict[str, str] = {}
        for e in evidence_items:
            eid = _dget(e, "id", "")
            if eid:
                evidence_map[str(eid)] = _get_temporal_level(e) or "unknown"

        cluster_map: dict[str, str] = {}
        for c in clusters:
            if isinstance(c, dict):
                cid = c.get("cluster_id", "")
                level = c.get("temporal_level", "unknown") or "unknown"
            else:
                cid = getattr(c, "cluster_id", "")
                level = getattr(c, "temporal_level", "unknown") or "unknown"
            if cid:
                cluster_map[str(cid)] = level
        return evidence_map, cluster_map

    @staticmethod
    def _resolve_gap_temporal(
        cluster_refs: list[str],
        evidence_refs: list[str],
        cluster_map: dict[str, str],
        evidence_map: dict[str, str],
    ) -> str:
        """Compute a gap's evidence_temporal_level.

        Priority: cluster.temporal_level; fallback: evidence_refs aggregation.
        """
        if cluster_refs:
            levels = [cluster_map.get(str(cr)) for cr in cluster_refs if cluster_map.get(str(cr))]
            if levels:
                return _aggregate_temporal_levels(levels)
        levels = [evidence_map.get(str(er)) for er in evidence_refs if evidence_map.get(str(er))]
        if levels:
            return _aggregate_temporal_levels(levels)
        return "unknown"

    async def arun(self, ctx: AgentContext, input_data: CompareInput) -> AgentResult:
        import time

        from app.infrastructure.agents.agent_io_compact import (
            COMPACT_EVIDENCE_CAP,
            COMPACT_SNIPPET_CHARS,
            compress_evidence_items,
        )
        from app.infrastructure.agents.compare_prompt import (
            COMPACT_SYSTEM_PROMPT,
            build_compare_prompt_compact,
            build_compare_repair_prompt,
        )
        from app.infrastructure.agents.timeout_stubs import try_parse_compare_llm_json
        from app.infrastructure.workflow.workflow_budget import split_primary_repair_timeouts

        self._partial_input = input_data
        self._partial_raw_text = ""
        t0 = time.monotonic()

        eb = input_data.evidence_bundle
        raw_items = _dget(eb, "evidence_items", []) or []
        clusters = list(input_data.evidence_clusters or [])
        compact = bool(getattr(input_data, "compact", True))
        research_incomplete = bool(getattr(input_data, "research_incomplete", False))

        if not raw_items and not clusters:
            return AgentResult(success=True, output=CompareOutput(
                gap_analysis=GapAnalysis(),
                evidence_references_count=0,
            ), phase_record={"phase": Phase.COMPARING.value, "status": "no_evidence"})

        if compact:
            packed = compress_evidence_items(
                raw_items, cap=COMPACT_EVIDENCE_CAP, snippet_chars=COMPACT_SNIPPET_CHARS,
            )
            evidence_json = json.dumps(packed, ensure_ascii=False)
            evidence_items = packed
            # Flat evidence path — skip large cluster payload for speed
            user_prompt = build_compare_prompt_compact(
                our_company=input_data.our_company,
                competitor_company=input_data.competitor_company,
                product=input_data.product,
                evidence_json=evidence_json,
                analysis_scope=input_data.analysis_scope,
                research_incomplete=research_incomplete,
            )
            system_prompt = COMPACT_SYSTEM_PROMPT
        else:
            evidence_items = sorted(raw_items, key=_evidence_sort_key)[:COMPARE_EVIDENCE_INPUT_CAP]
            evidence_json = json.dumps([
                {
                    "id": _dget(e, "id", ""), "title": _dget(e, "title", ""),
                    "source": _dget(e, "source", ""), "url": _dget(e, "url", ""),
                    "date": _dget(e, "date", ""), "dimension": _dget(e, "category", ""),
                    "summary": (_dget(e, "content", "") or "")[:300],
                    "confidence": _dget(e, "confidence", "estimated"),
                    "temporal_level": _get_temporal_level(e) or "unknown",
                }
                for e in evidence_items
            ], ensure_ascii=False, indent=2)
            clusters_json = json.dumps(clusters, ensure_ascii=False, indent=2)
            if clusters:
                user_prompt = build_cluster_compare_prompt(
                    our_company=input_data.our_company,
                    competitor_company=input_data.competitor_company,
                    product=input_data.product,
                    clusters_json=clusters_json,
                    evidence_json=evidence_json,
                    analysis_scope=input_data.analysis_scope,
                )
            else:
                user_prompt = build_compare_prompt(
                    our_company=input_data.our_company,
                    competitor_company=input_data.competitor_company,
                    product=input_data.product,
                    evidence_json=evidence_json,
                    analysis_scope=input_data.analysis_scope,
                )
            system_prompt = SYSTEM_PROMPT

        evidence_map, cluster_map = self._build_temporal_maps(raw_items, clusters)
        node_timeout = float(input_data.llm_timeout_seconds or 90.0)
        primary_t, repair_t = split_primary_repair_timeouts(node_timeout)

        parsed = None
        try:
            result = await llm_client.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_model=None,
                temperature=0.3 if compact else 0.4,
                timeout=primary_t if primary_t > 0 else None,
            )
            raw_text = (result.content or "").strip()
            self._partial_raw_text = raw_text
            parsed = try_parse_compare_llm_json(raw_text)
        except Exception:
            parsed = None

        if (not parsed or not (parsed.differences or parsed.capability_gaps)) and repair_t >= 8.0:
            broken = self._partial_raw_text or ""
            try:
                repair = await llm_client.generate(
                    system_prompt=COMPACT_SYSTEM_PROMPT if compact else SYSTEM_PROMPT,
                    user_prompt=build_compare_repair_prompt(broken or user_prompt[-1500:]),
                    response_model=None,
                    temperature=0.1,
                    timeout=repair_t,
                )
                raw_text = (repair.content or "").strip()
                if raw_text:
                    self._partial_raw_text = raw_text
                    parsed = try_parse_compare_llm_json(raw_text)
            except Exception:
                pass

        elapsed = round(time.monotonic() - t0, 2)

        if not parsed or not (parsed.differences or parsed.capability_gaps):
            return AgentResult(success=True, output=CompareOutput(
                gap_analysis=GapAnalysis(),
                evidence_references_count=len(evidence_items),
            ), phase_record={
                "phase": Phase.COMPARING.value, "status": "completed",
                "llm_generated": False,
                "compare_mode": "parse_fail",
                "compare_elapsed_s": elapsed,
                "note": "LLM returned empty/unparseable results",
            })

        gap = self._build_gap_analysis(parsed, evidence_items, cluster_map, evidence_map)
        all_refs = set()
        for d in parsed.differences:
            all_refs.update(d.evidence_refs)
        for cg in parsed.capability_gaps:
            all_refs.update(cg.evidence_refs)

        return AgentResult(success=True, output=CompareOutput(
            gap_analysis=gap,
            dimensions_analyzed=parsed.dimensions_analyzed,
            dimensions_skipped=[d.get("dimension", "") for d in parsed.dimensions_skipped],
            evidence_references_count=len(all_refs),
        ), phase_record={
            "phase": Phase.COMPARING.value, "status": "completed",
            "llm_generated": True,
            "compare_mode": "compact_agent" if compact else "full_agent",
            "compare_elapsed_s": elapsed,
            "differences_count": len(parsed.differences),
            "capability_gaps_count": len(parsed.capability_gaps),
        })

    def _build_gap_analysis(
        self,
        parsed,
        _evidence_items,
        cluster_map: dict[str, str] | None = None,
        evidence_map: dict[str, str] | None = None,
    ) -> GapAnalysis:
        cluster_map = cluster_map or {}
        evidence_map = evidence_map or {}
        fm = []
        for d in parsed.differences:
            cluster_refs = getattr(d, 'cluster_refs', []) or []
            fm.append(FeatureItem(
                category=d.dimension, feature_name=d.title,
                our_coverage=d.our_status, competitor_coverage=d.competitor_status,
                differentiator=True, evidence_refs=d.evidence_refs,
                cluster_refs=cluster_refs,
            ).model_dump())

        pos = {}
        pos_diffs = [d for d in parsed.differences if d.dimension == "positioning"]
        if pos_diffs:
            p = pos_diffs[0]
            pos = {"our_positioning": p.our_status, "competitor_positioning": p.competitor_status}

        return GapAnalysis(
            positioning=pos,
            features={"feature_matrix": fm, "overall_summary": parsed.overall_summary},
            gaps={
                "competitive_advantages": [GapItem(dimension="", description=a, impact="medium").model_dump() for a in parsed.advantages],
                "competitive_disadvantages": [GapItem(dimension="", description=d, impact="high").model_dump() for d in parsed.disadvantages],
                "capability_gaps": [GapItem(
                    dimension=cg.dimension,
                    description=f"{cg.title}: 我={cg.our_status} vs 竞={cg.competitor_status}. 用户:{cg.user_impact}. 业务:{cg.business_impact}",
                    evidence_refs=cg.evidence_refs,
                    cluster_refs=getattr(cg, "cluster_refs", []) or [],
                    impact="high",
                    evidence_temporal_level=self._resolve_gap_temporal(
                        getattr(cg, "cluster_refs", []) or [],
                        cg.evidence_refs,
                        cluster_map,
                        evidence_map,
                    ),
                ).model_dump() for cg in parsed.capability_gaps],
            },
            evidence_references=sorted(set(ref for d in parsed.differences for ref in d.evidence_refs)),
        )
