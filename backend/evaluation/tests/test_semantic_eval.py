"""Tests for Semantic Reasoning Critic V1 (mock LLM responses)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from evaluation.semantic_eval import SemanticReasoningEvaluator
from evaluation.quality_evaluator import evaluate, evaluate_async


class FakeResponse:
    def __init__(self, content: str):
        self.content = content


class MockLLM:
    def __init__(self, responses: list):
        self._responses = list(responses)

    async def generate(self, *args, **kwargs):
        content = self._responses.pop(0)
        if isinstance(content, Exception):
            raise content
        return FakeResponse(content)


def _input(insights=None) -> dict:
    return {
        "evidence_items": [
            {"id": "E1", "title": "App Store 评分 4.83", "content": "飞猪 App Store 评分 4.83/5"},
        ],
        "insights": insights
        or [
            {"type": "hypothesis", "confidence": "high", "description": "飞猪用户体验领先", "evidence_refs": ["E1"], "cluster_refs": []},
        ],
    }


def _run(coro):
    return asyncio.run(coro)


class TestSemanticEvaluation:
    def test_evidence_directly_supports(self):
        llm = MockLLM(['{"score": 90, "issue_type": "supported", "explanation": "评分证据直接支持"}'])
        result = _run(SemanticReasoningEvaluator(llm_client=llm).evaluate(_input()))
        assert result is not None
        assert result.score > 80
        assert result.details["supported_count"] == 1

    def test_evidence_weakly_supports(self):
        llm = MockLLM(['{"score": 60, "issue_type": "weak_support", "explanation": "仅部分相关"}'])
        result = _run(SemanticReasoningEvaluator(llm_client=llm).evaluate(_input()))
        assert result is not None
        assert 50 <= result.score <= 80
        assert result.details["weak_support_count"] == 1

    def test_evidence_contradicts(self):
        llm = MockLLM(['{"score": 30, "issue_type": "contradiction", "explanation": "证据与结论矛盾"}'])
        result = _run(SemanticReasoningEvaluator(llm_client=llm).evaluate(_input()))
        assert result is not None
        assert result.score < 50
        assert result.details["contradiction_count"] == 1

    def test_llm_failure_returns_none(self):
        llm = MockLLM([RuntimeError("LLM down")])
        result = _run(SemanticReasoningEvaluator(llm_client=llm).evaluate(_input()))
        assert result is None


class TestCostControl:
    def test_max_insights_selection_prioritizes_high_hypothesis(self):
        insights = [
            {"type": "fact", "confidence": "high", "description": "f1", "evidence_refs": ["E1"], "cluster_refs": []},
            {"type": "fact", "confidence": "high", "description": "f2", "evidence_refs": ["E1"], "cluster_refs": []},
            {"type": "observation", "confidence": "medium", "description": "o1", "evidence_refs": ["E1"], "cluster_refs": []},
            {"type": "hypothesis", "confidence": "medium", "description": "h1", "evidence_refs": ["E1"], "cluster_refs": []},
            {"type": "hypothesis", "confidence": "high", "description": "h2", "evidence_refs": ["E1"], "cluster_refs": []},
        ]
        selected = SemanticReasoningEvaluator._select_insights(insights, 3)
        # high-confidence hypothesis first, then other hypothesis, then observation
        assert selected[0]["description"] == "h2"
        assert selected[1]["description"] == "h1"
        assert selected[2]["description"] == "o1"
        assert len(selected) == 3


class TestOrchestration:
    def _base_input(self) -> dict:
        return {
            "evidence_items": [
                {"id": "E1", "title": "App Store 评分 4.83", "content": "评分证据"},
            ],
            "insights": [
                {
                    "type": "hypothesis",
                    "confidence": "high",
                    "description": "飞猪用户体验领先",
                    "evidence_refs": ["E1"],
                    "cluster_refs": [],
                },
            ],
            "recommendations": [
                {"action": "a1", "evidence_refs": ["E1"], "cluster_refs": []},
            ],
            "markdown": "# report",
        }

    def test_async_adds_semantic_metric_and_recomputes_overall(self):
        llm = MockLLM(['{"score": 80, "issue_type": "supported", "explanation": "支持"}'])
        result = _run(
            evaluate_async(self._base_input(), llm_client=llm, max_insights=5)
        )
        assert "semantic_reasoning" in result.metrics
        assert result.metrics["semantic_reasoning"]["score"] == 80.0
        # 7 scored metrics now (6 deterministic + semantic)
        scored = [
            m["score"]
            for m in result.metrics.values()
            if isinstance(m, dict) and m.get("score") is not None
        ]
        assert len(scored) == 7
        assert result.overall_score == round(sum(scored) / 7, 2)

    def test_async_omits_semantic_when_llm_fails(self):
        llm = MockLLM([RuntimeError("down")])
        result = _run(
            evaluate_async(self._base_input(), llm_client=llm, max_insights=5)
        )
        assert "semantic_reasoning" not in result.metrics

    def test_sync_evaluate_unchanged(self):
        result = evaluate(self._base_input())
        assert "semantic_reasoning" not in result.metrics
