"""Copilot dependency providers."""

from __future__ import annotations

from functools import lru_cache

from app.application.services.conversation_service import ConversationService
from app.application.services.intent_understanding_service import IntentUnderstandingService
from app.application.services.project_service import ProjectService
from app.infrastructure.persistence.copilot.stores import ConversationStore, MessageStore, ProjectStore


@lru_cache
def get_project_store() -> ProjectStore:
    return ProjectStore()


@lru_cache
def get_conversation_store() -> ConversationStore:
    return ConversationStore()


@lru_cache
def get_message_store() -> MessageStore:
    return MessageStore()


@lru_cache
def get_project_memory_store():
    from app.infrastructure.persistence.copilot.project_memory_store import ProjectMemoryStore

    return ProjectMemoryStore()


@lru_cache
def get_memory_writer():
    from app.application.services.memory_writer import MemoryWriter

    return MemoryWriter(store=get_project_memory_store())


@lru_cache
def get_memory_service():
    from app.application.services.memory_service import MemoryService

    return MemoryService(
        memory_store=get_project_memory_store(),
        project_store=get_project_store(),
    )


@lru_cache
def get_knowledge_notes_store():
    from app.infrastructure.persistence.copilot.knowledge_notes_store import KnowledgeNotesStore

    return KnowledgeNotesStore()


@lru_cache
def get_knowledge_service():
    from app.application.services.knowledge_service import KnowledgeService

    return KnowledgeService(
        notes_store=get_knowledge_notes_store(),
        project_store=get_project_store(),
    )


@lru_cache
def get_intent_understanding_service() -> IntentUnderstandingService:
    return IntentUnderstandingService()


@lru_cache
def get_project_service() -> ProjectService:
    from app.interfaces.api.dependencies.workflow import get_artifact_store

    return ProjectService(
        store=get_project_store(),
        conversation_store=get_conversation_store(),
        message_store=get_message_store(),
        artifact_store=get_artifact_store(),
    )


def get_conversation_service() -> ConversationService:
    from app.interfaces.api.dependencies.workflow import (
        get_collection_workflow_launcher,
        get_workflow_launcher,
    )
    from app.infrastructure.events.conversation_event_bus import get_conversation_event_bus

    return ConversationService(
        conversation_store=get_conversation_store(),
        message_store=get_message_store(),
        project_service=get_project_service(),
        intent_service=get_intent_understanding_service(),
        workflow_launcher=get_workflow_launcher(),
        collection_launcher=get_collection_workflow_launcher(),
        event_bus=get_conversation_event_bus(),
        memory_store=get_project_memory_store(),
        knowledge_service=get_knowledge_service(),
    )
