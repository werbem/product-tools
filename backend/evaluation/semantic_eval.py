"""Semantic Reasoning Critic V1 (offline, optional LLM).

Evaluates whether evidence logically supports each insight conclusion.
This is the ONLY evaluation-stage component allowed to call an LLM.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field


_SYSTEM_PROMPT = """你是严格的竞品分析推理审核员。

你的任务：判断给定证据是否逻辑上充分支持给定的洞察结论。

issue_type 判定：
- supported：证据直接支持结论
- weak_support：证据仅部分相关，支撑较弱
- over_inference：证据不支撑结论，属于过度推断
- contradiction：证据与结论矛盾

严格输出 JSON（不要输出其他内容）：
{
  "score": 0-100,
  "issue_type": "supported" | "weak_support" | "over_inference" | "contradiction",
  "explanation": "一句话说明"
}"""


@dataclass
class SemanticReasoningResult:
    score: float | None
    details: dict = field(default_factory=dict)


class SemanticReasoningEvaluator:
    """Semantically evaluate evidence→insight support using an LLM.

    The LLM client is injectable for testing; by default it lazily imports the
    production `llm_client`. On any LLM failure this returns None without
    breaking the surrounding evaluation pipeline.
    """

    def __init__(self, llm_client=None, max_insights: int = 5):
        self._llm_client = llm_client
        self._max_insights = max_insights

    def _get_llm_client(self):
        if self._llm_client is not None:
            return self._llm_client
        try:
            from app.infrastructure.llm.client import llm_client
            return llm_client
        except Exception:
            return None

    @staticmethod
    def _priority(insight: dict) -> int:
        insight_type = insight.get("type", "")
        confidence = insight.get("confidence", "")
        if insight_type == "hypothesis" and confidence == "high":
            return 0
        if insight_type == "hypothesis":
            return 1
        if insight_type == "observation":
            return 2
        return 3  # fact / unknown

    @staticmethod
    def _select_insights(insights: list[dict], max_insights: int) -> list[dict]:
        return sorted(
            insights, key=SemanticReasoningEvaluator._priority
        )[:max_insights]

    @staticmethod
    def _evidence_for(evidence_items: list[dict], insight: dict) -> list[dict]:
        refs = {str(r) for r in (insight.get("evidence_refs", []) or [])}
        return [
            {
                "id": e.get("id", ""),
                "title": e.get("title", ""),
                "content": (e.get("content", "") or e.get("summary", ""))[:200],
            }
            for e in evidence_items
            if str(e.get("id", "")) in refs
        ]

    @staticmethod
    def _build_user_prompt(evidence: list[dict], insight: dict) -> str:
        evidence_json = json.dumps(evidence, ensure_ascii=False, indent=2)
        return (
            "## 证据（Evidence）\n"
            f"{evidence_json}\n\n"
            "## 洞察（Insight）\n"
            f"类型: {insight.get('type', '')}\n"
            f"置信度: {insight.get('confidence', '')}\n"
            f"结论: {insight.get('description', '')}\n\n"
            "## 问题\n"
            "证据是否充分支持该洞察结论？\n"
            '请输出 JSON：{"score": 0-100, "issue_type": "...", "explanation": "..."}'
        )

    @staticmethod
    def _parse_response(raw: str) -> dict | None:
        if not raw:
            return None
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
            if isinstance(data, dict) and "score" in data:
                return data
        except json.JSONDecodeError:
            pass
        m = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group())
                if isinstance(data, dict) and "score" in data:
                    return data
            except json.JSONDecodeError:
                pass
        return None

    async def evaluate(
        self,
        normalized_input: dict,
    ) -> SemanticReasoningResult | None:
        llm = self._get_llm_client()
        if llm is None:
            return None

        insights = normalized_input.get("insights", []) or []
        evidence_items = normalized_input.get("evidence_items", []) or []
        selected = self._select_insights(insights, self._max_insights)

        parsed_results: list[dict] = []
        for insight in selected:
            evidence = self._evidence_for(evidence_items, insight)
            user_prompt = self._build_user_prompt(evidence, insight)
            try:
                response = await llm.generate(
                    system_prompt=_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    temperature=0.1,
                )
                parsed = self._parse_response(
                    getattr(response, "content", "") or ""
                )
                if parsed:
                    parsed_results.append(parsed)
            except Exception:
                # LLM failure on a single insight is non-fatal
                continue

        if not parsed_results:
            return None

        scores = [
            r["score"]
            for r in parsed_results
            if isinstance(r.get("score"), (int, float))
        ]
        if not scores:
            return None

        score = round(sum(scores) / len(scores), 2)
        details = {
            "evaluated_insights": len(parsed_results),
            "supported_count": sum(
                1 for r in parsed_results if r.get("issue_type") == "supported"
            ),
            "weak_support_count": sum(
                1 for r in parsed_results if r.get("issue_type") == "weak_support"
            ),
            "over_inference_count": sum(
                1 for r in parsed_results if r.get("issue_type") == "over_inference"
            ),
            "contradiction_count": sum(
                1 for r in parsed_results if r.get("issue_type") == "contradiction"
            ),
        }
        return SemanticReasoningResult(score=score, details=details)
