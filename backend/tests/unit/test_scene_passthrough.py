"""Step 38: scene passthrough for collect Gate + deep-analysis alignment."""

from __future__ import annotations

import pytest

from app.application.dto.agent_dto import GateInput, UserInputDTO
from app.application.dto.report_dto import ReportCreateRequest
from app.application.services.intent_mapper import to_report_create_request
from app.application.dto.intent_dto import IntentUnderstandingResult
from app.infrastructure.agents.base import AgentContext
from app.infrastructure.agents.gate_agent import GateAgent
from app.infrastructure.workflow.collect_graph import collect_validate_node


@pytest.mark.asyncio
async def test_gate_reads_scene_as_effective_objective():
    agent = GateAgent()
    result = await agent.arun(
        AgentContext(task_id="t-scene", current_phase="validating"),
        GateInput(
            user_input=UserInputDTO(
                our_company="字节跳动",
                competitor_company="公开市场与主要竞品",
                product="抖音",
                objective="product_improvement",
                scene="收集字节跳动抖音近期商业发展信息",
                optional={"raw_message": "帮我收集字节跳动抖音近期商业发展信息"},
            )
        ),
    )
    assert result.success
    values = result.output.validated_input.clean_values
    assert values["objective"] == "收集字节跳动抖音近期商业发展信息"
    assert values["scene"] == "收集字节跳动抖音近期商业发展信息"
    assert values["objective_code"] == "product_improvement"
    assert values["raw_message"] == "帮我收集字节跳动抖音近期商业发展信息"


@pytest.mark.asyncio
async def test_collect_validate_passes_scene_to_gate():
    state = {
        "task_id": "collect-scene",
        "user_input": {
            "our_company": "字节跳动",
            "competitor_company": "公开市场与主要竞品",
            "product": "抖音",
            "objective": "product_improvement",
            "scene": "收集字节跳动抖音近期商业发展信息",
            "optional": {
                "raw_message": "帮我收集字节跳动抖音近期商业发展信息",
                "workflow_kind": "intelligence_collection",
            },
        },
        "phase_history": [],
        "errors": [],
        "retry_counts": {},
    }
    update = await collect_validate_node(state)
    assert update["current_phase"] == "validated"
    validated = update["validated_input"]
    assert validated["scene"] == "收集字节跳动抖音近期商业发展信息"
    assert validated["objective"] == "收集字节跳动抖音近期商业发展信息"
    assert validated["objective_code"] == "product_improvement"


@pytest.mark.asyncio
async def test_deep_analysis_scene_passthrough_unchanged():
    """Deep analysis still prefers scene over objective enum."""
    agent = GateAgent()
    result = await agent.arun(
        AgentContext(task_id="t-deep", current_phase="validating"),
        GateInput(
            user_input=UserInputDTO(
                our_company="飞猪",
                competitor_company="美团",
                product="酒店",
                objective="product_improvement",
                scene="Compare hotel booking UX gaps",
            )
        ),
    )
    values = result.output.validated_input.clean_values
    assert values["objective"] == "Compare hotel booking UX gaps"
    assert values["scene"] == "Compare hotel booking UX gaps"
    assert values["objective_code"] == "product_improvement"


def test_intent_mapper_still_sets_scene_for_intel():
    intent = IntentUnderstandingResult(
        type="competitive_analysis",
        company="字节跳动",
        competitors=[],
        product="抖音",
        objective="intelligence_collection",
        needs_clarification=False,
        confidence=0.9,
        raw_message="帮我收集字节跳动抖音近期商业发展信息",
    )
    req: ReportCreateRequest = to_report_create_request(intent, analysis_mode="fast")
    assert req.scene == "帮我收集字节跳动抖音近期商业发展信息"
    assert req.objective == "product_improvement"
    assert req.optional.get("workflow_kind") == "intelligence_collection"
