"""Decision Architecture contracts (Phase 1).

Parallel to legacy IntentUnderstandingResult / RoutingDecision.
Production path is not switched until Phase 5.
"""

from app.application.dto.decision.adapters import (
    execution_plan_to_routing_decision,
    legacy_intent_to_decision_entities,
    routing_context_to_decision_context,
    workflow_type_to_execution_mode_hint,
)
from app.application.dto.decision.context_contract import DecisionContext
from app.application.dto.decision.entity_contract import (
    ENTITY_SLOT_NAMES,
    DecisionEntities,
    EntitySlot,
    EntitySource,
)
from app.application.dto.decision.intent_contract import (
    AskSubtype,
    DecisionIntent,
    Discourse,
    TaskFamily,
)
from app.application.dto.decision.plan_contract import (
    ExecutionMode,
    ExecutionPlan,
    PlanStep,
    PlanWorkflowType,
)

__all__ = [
    "AskSubtype",
    "DecisionContext",
    "DecisionEntities",
    "DecisionIntent",
    "Discourse",
    "ENTITY_SLOT_NAMES",
    "EntitySlot",
    "EntitySource",
    "ExecutionMode",
    "ExecutionPlan",
    "PlanStep",
    "PlanWorkflowType",
    "TaskFamily",
    "execution_plan_to_routing_decision",
    "legacy_intent_to_decision_entities",
    "routing_context_to_decision_context",
    "workflow_type_to_execution_mode_hint",
]
