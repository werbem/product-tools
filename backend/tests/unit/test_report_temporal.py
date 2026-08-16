"""Unit tests for Report Agent temporal consumption (Step 5)."""

from __future__ import annotations

import json

from app.infrastructure.agents.report_agent import ReportAgent


class TestSerializeGapTemporal:
    def test_capability_gaps_include_temporal(self):
        gap = {
            "positioning": {},
            "features": {"feature_matrix": []},
            "gaps": {
                "capability_gaps": [
                    {"description": "d1", "evidence_refs": ["E1"], "evidence_temporal_level": "historical"},
                ],
                "competitive_advantages": [],
                "competitive_disadvantages": [],
            },
        }
        data = json.loads(ReportAgent._serialize_gap(gap))
        assert data["capability_gaps"][0]["evidence_temporal_level"] == "historical"

    def test_capability_gaps_old_data_fallback_unknown(self):
        gap = {
            "positioning": {},
            "features": {"feature_matrix": []},
            "gaps": {
                "capability_gaps": [
                    {"description": "d1", "evidence_refs": ["E1"]},
                ],
                "competitive_advantages": [],
                "competitive_disadvantages": [],
            },
        }
        data = json.loads(ReportAgent._serialize_gap(gap))
        assert data["capability_gaps"][0]["evidence_temporal_level"] == "unknown"


class TestSerializeStrategyTemporal:
    def test_recommendations_include_temporal(self):
        strategy = {
            "swot": {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
            "opportunities": [],
            "risks": [],
            "recommendations": [
                {"action": "a1", "rationale": "r1", "evidence_temporal_level": "historical"},
            ],
            "roadmap": {"phases": []},
        }
        data = json.loads(ReportAgent._serialize_strategy(strategy))
        assert data["recommendations"][0]["evidence_temporal_level"] == "historical"

    def test_recommendations_old_data_fallback_unknown(self):
        strategy = {
            "swot": {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
            "opportunities": [],
            "risks": [],
            "recommendations": [
                {"action": "a1", "rationale": "r1"},
            ],
            "roadmap": {"phases": []},
        }
        data = json.loads(ReportAgent._serialize_strategy(strategy))
        assert data["recommendations"][0]["evidence_temporal_level"] == "unknown"


class TestPromptContainsTemporal:
    def test_historical_recommendation_in_prompt(self):
        strategy = {
            "swot": {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []},
            "opportunities": [],
            "risks": [],
            "recommendations": [
                {"action": "a1", "rationale": "r1", "evidence_temporal_level": "historical"},
            ],
            "roadmap": {"phases": []},
        }
        strategy_json = ReportAgent._serialize_strategy(strategy)
        # 序列化结果会作为 strategy_json 进入 build_report_prompt
        assert '"evidence_temporal_level": "historical"' in strategy_json
