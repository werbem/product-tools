"""Workflow dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.application.services.artifact_service import ArtifactService
from app.application.services.collection_workflow_launcher import CollectionWorkflowLauncher
from app.application.services.workflow_launcher import DeepAnalysisWorkflowLauncher
from app.infrastructure.events.conversation_event_bus import get_conversation_event_bus
from app.infrastructure.persistence.copilot.stores import ArtifactStore


@lru_cache
def get_artifact_store() -> ArtifactStore:
    return ArtifactStore()


@lru_cache
def get_artifact_service() -> ArtifactService:
    return ArtifactService(get_artifact_store())


@lru_cache
def get_collection_workflow_launcher() -> CollectionWorkflowLauncher:
    from app.interfaces.api.dependencies.copilot import get_memory_writer

    return CollectionWorkflowLauncher(
        event_bus=get_conversation_event_bus(),
        artifact_service=get_artifact_service(),
        memory_writer=get_memory_writer(),
    )


@lru_cache
def get_workflow_launcher() -> DeepAnalysisWorkflowLauncher:
    from app.interfaces.api.dependencies.copilot import get_memory_writer

    return DeepAnalysisWorkflowLauncher(
        event_bus=get_conversation_event_bus(),
        artifact_service=get_artifact_service(),
        memory_writer=get_memory_writer(),
    )
