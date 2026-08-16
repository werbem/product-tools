"""Evidence Clustering — aggregate multiple evidence into topic clusters.

Groups related evidence items into semantic topic clusters using LLM.
Each cluster preserves source diversity and confidence metadata.

Why cluster evidence:
  - CompareAgent sees coherent topic groups instead of scattered items
  - Source diversity per cluster enriches gap analysis
  - Confidence per cluster filters low-quality aggregations

Architecture:
  EvidenceItem list
      ↓
  EvidenceClusteringEngine.cluster()
      ↓
  EvidenceCluster[]  (topic + evidence_refs + summary + confidence)
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
from uuid import uuid4

from app.infrastructure.tools.research_source import SourceType


# Temporal tiers (order used for the 70% dominance rule).
_TEMPORAL_TIERS: list[str] = ["recent", "aging", "stale", "historical", "unknown"]


def _temporal_from_date(date_str: str) -> str:
    """Year-based temporal level fallback when temporal_level is absent."""
    if not date_str:
        return "unknown"
    m = re.search(r"(20\d{2})", str(date_str))
    if not m:
        return "unknown"
    try:
        year = int(m.group(1))
    except (ValueError, TypeError):
        return "unknown"
    age = datetime.now().year - year
    if age < 1:
        return "recent"
    if age < 3:
        return "aging"
    if age < 5:
        return "stale"
    return "historical"


# ═══════════════════════════════════════════════════
#  Cluster Model
# ═══════════════════════════════════════════════════

@dataclass
class EvidenceCluster:
    """A topic cluster containing related evidence items from multiple sources."""
    cluster_id: str = field(default_factory=lambda: str(uuid4()))
    topic: str = ""                       # 主题名称 (e.g. "会员体系变化")
    evidence_refs: list[str] = field(default_factory=list)  # EvidenceItem IDs
    summary: str = ""                     # 聚类摘要 (1-2 sentences)
    confidence: float = 0.0              # 0-1, cluster average confidence
    source_diversity: dict[str, int] = field(default_factory=dict)  # source_type → count
    evidence_count: int = 0
    temporal_level: str = "unknown"       # recent|aging|stale|historical|mixed|unknown
    temporal_distribution: dict = field(default_factory=dict)  # tier -> count

    def to_dict(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "topic": self.topic,
            "evidence_refs": self.evidence_refs,
            "summary": self.summary,
            "confidence": round(self.confidence, 2),
            "source_diversity": self.source_diversity,
            "evidence_count": self.evidence_count,
            "temporal_level": self.temporal_level,
            "temporal_distribution": self.temporal_distribution,
        }


# ═══════════════════════════════════════════════════
#  Clustering Prompts
# ═══════════════════════════════════════════════════

CLUSTERING_SYSTEM_PROMPT = """你是竞品分析证据聚类专家。将多条证据按事实主题分组。

## 聚类原则

1. **主题驱动**: 同一事实主题的证据归为一类
   例如: "会员体系变化" 可以包含官方公告、新闻报道、用户讨论
2. **源多样性**: 同主题下尽量保留多种数据源（官方+新闻+社交+App评论）
3. **置信度**: 每个聚类给出 0-1 置信度（基于证据质量和一致性）
4. **粒度适中**: 每类 2-5 条证据（不要每证据一个类，也不要所有证据一个类）

## 输出格式 (JSON)

{
  "clusters": [
    {
      "topic": "主题名称",
      "evidence_refs": ["e1", "e3"],
      "summary": "一句话总结该主题发现",
      "confidence": 0.85
    }
  ]
}

注意:
- 每条证据只能属于一个聚类
- 未归类的孤立证据也单独成簇
- 使用evidence id引用（e1, e2, ...）
- 只返回 JSON，不要其他文本"""

CLUSTERING_USER_TEMPLATE = """## 分析目标
{objective}

## 待聚类证据 ({count}条)

{evidence_text}

请将上述证据聚类为 3-6 个事实主题。只返回 JSON。"""


# ═══════════════════════════════════════════════════
#  Clustering Engine
# ═══════════════════════════════════════════════════

class EvidenceClusteringEngine:
    """LLM-powered evidence clustering.

    Groups scattered evidence items into coherent topic clusters
    while preserving source diversity and confidence metadata.
    """

    DEFAULT_MAX_CLUSTERS = 6
    DEFAULT_MIN_CLUSTERS = 2

    async def cluster(
        self,
        evidence_items: list[dict],
        objective: str = "",
    ) -> list[EvidenceCluster]:
        """Cluster evidence items into topic groups.

        Args:
            evidence_items: List of evidence dicts with keys:
                id, title, content, source_type, confidence
            objective: Research question for context

        Returns:
            List of EvidenceCluster with topic groupings
        """
        if not evidence_items:
            return []

        if len(evidence_items) <= 2:
            # Too few to cluster meaningfully, return one cluster
            return [self._make_single_cluster(evidence_items)]

        # Build LLM prompt
        evidence_text = self._format_evidence(evidence_items)
        user_prompt = CLUSTERING_USER_TEMPLATE.format(
            objective=objective or "竞品分析",
            count=len(evidence_items),
            evidence_text=evidence_text,
        )

        try:
            from app.infrastructure.llm.client import llm_client

            response = await llm_client.generate(
                system_prompt=CLUSTERING_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                temperature=0.2,  # Low temp for deterministic clustering
            )

            if response.content:
                clusters_data = self._parse_clusters(response.content)
                if clusters_data:
                    built = self._build_clusters(clusters_data, evidence_items)
                    if built:
                        return built

        except Exception:
            pass  # Fallback to single-cluster grouping

        # Fallback: single cluster with all evidence
        return [self._make_single_cluster(evidence_items)]

    # ── Internals ──

    @staticmethod
    def _format_evidence(items: list[dict]) -> str:
        """Format evidence list for LLM prompt."""
        lines = []
        for item in items:
            eid = item.get("id", "?")
            title = item.get("title", "")[:80]
            stype = item.get("source_type", "unknown")
            conf = item.get("confidence", "medium")
            date = item.get("date", "")
            temporal = item.get("temporal_level", "")
            content = (item.get("content", "") or "")[:200]
            lines.append(
                f"[{eid}] type={stype} conf={conf} date={date or '?'} temporal={temporal or '?'}\n"
                f"  标题: {title}\n"
                f"  内容: {content}\n"
            )
        return "\n".join(lines)

    @staticmethod
    def _compute_temporal_aggregation(items: list[dict]) -> tuple[str, dict]:
        """Aggregate member temporal_level into a cluster-level level + distribution.

        Rule: if a single tier covers >= 70% of evidence, that tier wins;
        otherwise the cluster is "mixed".
        """
        dist: dict[str, int] = {t: 0 for t in _TEMPORAL_TIERS}
        for item in items:
            level = item.get("temporal_level") or _temporal_from_date(
                item.get("date", "")
            )
            if level not in dist:
                level = "unknown"
            dist[level] += 1

        total = sum(dist.values())
        cluster_level = "mixed"
        if total > 0:
            for tier in _TEMPORAL_TIERS:
                if dist[tier] / total >= 0.70:
                    cluster_level = tier
                    break
        return cluster_level, dist

    @staticmethod
    def _parse_clusters(raw: str) -> Optional[list[dict]]:
        """Parse LLM JSON response with multiple fallback strategies."""
        import json
        parsed: Optional[dict] = None

        # Strategy 1: Extract JSON from ```json ... ``` code block
        code_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', raw, re.DOTALL)
        if code_match:
            try:
                parsed = json.loads(code_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Strategy 2: Direct JSON parse
        if parsed is None:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                pass

        # Strategy 3: Find JSON object with "clusters" key
        if parsed is None:
            json_match = re.search(r'\{"clusters"\s*:\s*\[[\s\S]*?\]\}', raw)
            if json_match:
                try:
                    parsed = json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

        # Strategy 4: Find any JSON array with topic/evidence_refs keys
        if parsed is None:
            arr_match = re.search(r'\[\s*\{.*?"topic".*?"evidence_refs".*?\}', raw, re.DOTALL)
            if arr_match:
                try:
                    parsed = {"clusters": json.loads(arr_match.group())}
                except json.JSONDecodeError:
                    pass

        return parsed.get("clusters", []) if parsed else None

    @staticmethod
    def _build_clusters(
        clusters_data: list[dict],
        evidence_items: list[dict],
    ) -> list[EvidenceCluster]:
        """Build EvidenceCluster objects from LLM output + evidence items.

        Resolves LLM's evidence_refs back to evidence items, then recomputes
        source diversity, confidence, and temporal metadata per cluster.
        """
        # id -> item, plus 1-based positional map for the prompt's "e1, e2, ..."
        id_map: dict[str, dict] = {
            str(item.get("id", "")): item
            for item in evidence_items
            if item.get("id")
        }
        pos_map: dict[str, dict] = {
            f"e{i + 1}": item for i, item in enumerate(evidence_items)
        }

        clusters: list[EvidenceCluster] = []
        for c in clusters_data:
            if not isinstance(c, dict):
                continue
            refs = c.get("evidence_refs", []) or []
            members: list[dict] = []
            for ref in refs:
                item = id_map.get(str(ref)) or pos_map.get(str(ref))
                if item is not None:
                    members.append(item)
            if not members:
                continue  # skip empty/unresolvable cluster

            topic = c.get("topic", "") or ""
            summary = c.get("summary", "") or ""

            # Confidence: prefer LLM value, else derive from member confidence.
            llm_conf = c.get("confidence")
            if isinstance(llm_conf, (int, float)):
                confidence = max(0.0, min(1.0, float(llm_conf)))
            else:
                conf_map = {"high": 0.85, "medium": 0.60, "low": 0.35, "estimated": 0.20}
                confs = [
                    conf_map.get(m.get("confidence", "medium"), 0.50)
                    for m in members
                ]
                confidence = sum(confs) / max(len(confs), 1)

            source_counts: dict[str, int] = {}
            for m in members:
                st = m.get("source_type", "unknown")
                source_counts[st] = source_counts.get(st, 0) + 1

            temporal_level, temporal_distribution = (
                EvidenceClusteringEngine._compute_temporal_aggregation(members)
            )

            clusters.append(EvidenceCluster(
                topic=topic,
                evidence_refs=[m.get("id", "") for m in members],
                summary=summary,
                confidence=round(confidence, 2),
                source_diversity=source_counts,
                evidence_count=len(members),
                temporal_level=temporal_level,
                temporal_distribution=temporal_distribution,
            ))

        return clusters

    @staticmethod
    def _make_single_cluster(items: list[dict]) -> EvidenceCluster:
        """Create a single cluster from all evidence (fallback)."""
        source_counts: dict[str, int] = {}
        for item in items:
            st = item.get("source_type", "unknown")
            source_counts[st] = source_counts.get(st, 0) + 1

        confidences = []
        conf_map = {"high": 0.85, "medium": 0.60, "low": 0.35, "estimated": 0.20}
        for item in items:
            confidences.append(conf_map.get(item.get("confidence", "medium"), 0.50))

        temporal_level, temporal_distribution = (
            EvidenceClusteringEngine._compute_temporal_aggregation(items)
        )

        return EvidenceCluster(
            topic="综合证据",
            evidence_refs=[i.get("id", "") for i in items],
            summary=f"共 {len(items)} 条证据",
            confidence=round(sum(confidences) / max(len(confidences), 1), 2),
            source_diversity=source_counts,
            evidence_count=len(items),
            temporal_level=temporal_level,
            temporal_distribution=temporal_distribution,
        )


# ── Singleton ──

evidence_clustering = EvidenceClusteringEngine()
