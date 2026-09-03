"""Gate Agent — input validation and normalization."""

from app.application.dto.agent_dto import GateInput, GateOutput, ValidatedInputDTO
from app.application.services.collection_topic import KNOWN_OBJECTIVE_CODES
from app.config.constants import Phase
from app.infrastructure.agents.base import AgentContext, AgentResult, BaseAgent


class GateAgent(BaseAgent[GateInput, GateOutput]):

    @property
    def agent_name(self) -> str:
        return "gate"

    @property
    def phase(self) -> Phase:
        return Phase.VALIDATING

    async def arun(self, ctx: AgentContext, input_data: GateInput) -> AgentResult:
        """Validate and normalize user input.

        Merges scene/additional_objective into the final objective field
        so downstream agents receive a unified objective context.
        Effective objective = scene or additional_objective or objective.
        """
        raw = input_data.user_input.model_dump()

        # Resolve objective: prefer scene > additional_objective > raw objective
        raw_objective = raw.get("objective", "product_improvement") or "product_improvement"
        scene = (raw.get("scene") or "").strip()
        optional = raw.get("optional") or {}
        if not isinstance(optional, dict):
            optional = {}
        additional = (optional.get("additional_objective") or "").strip()
        raw_message = (optional.get("raw_message") or "").strip()

        objective_code = raw_objective if raw_objective in KNOWN_OBJECTIVE_CODES else ""

        # effective_objective = scene or objective (aligned with deep-analysis launcher)
        if scene:
            objective = scene
        elif additional:
            objective = additional
        else:
            objective = raw_objective

        validated = ValidatedInputDTO(
            is_valid=True,
            clean_values={
                "our_company": raw.get("our_company", ""),
                "competitor_company": raw.get("competitor_company", ""),
                "product": raw.get("product", ""),
                "objective": objective,
                "scene": scene or additional or None,
                "objective_code": objective_code or None,
                "raw_message": raw_message or None,
            },
            issues=[],
        )
        output = GateOutput(
            validated_input=validated,
            current_phase=Phase.VALIDATED.value,
        )
        return AgentResult(success=True, output=output)
