"""In-memory conversation event bus."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import AsyncIterator

from app.application.dto.conversation_event_dto import ConversationEvent

logger = logging.getLogger(__name__)

QUEUE_MAX = 100
HEARTBEAT_SECONDS = 30.0
TERMINAL_EVENTS = frozenset({"artifact_created", "analysis_completed", "analysis_failed"})


class ConversationEventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue[ConversationEvent | None]]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def publish(self, event: ConversationEvent) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(event.conversation_id, []))
        for queue in queues:
            try:
                if queue.full():
                    if event.event in TERMINAL_EVENTS:
                        queue.put_nowait(event)
                    else:
                        try:
                            queue.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                        queue.put_nowait(event)
                else:
                    queue.put_nowait(event)
            except Exception:
                logger.exception("failed to publish event to subscriber")

    async def subscribe(self, conversation_id: str) -> AsyncIterator[ConversationEvent]:
        queue: asyncio.Queue[ConversationEvent | None] = asyncio.Queue(maxsize=QUEUE_MAX)
        async with self._lock:
            self._subscribers[conversation_id].append(queue)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except asyncio.TimeoutError:
                    yield ConversationEvent(
                        event="heartbeat",
                        conversation_id=conversation_id,
                        timestamp=datetime.now(timezone.utc),
                        data={},
                    )
                    continue
                if event is None:
                    break
                yield event
        finally:
            async with self._lock:
                subs = self._subscribers.get(conversation_id, [])
                if queue in subs:
                    subs.remove(queue)

    async def unsubscribe_all(self, conversation_id: str) -> None:
        async with self._lock:
            for queue in self._subscribers.get(conversation_id, []):
                await queue.put(None)


_event_bus: ConversationEventBus | None = None


def get_conversation_event_bus() -> ConversationEventBus:
    global _event_bus
    if _event_bus is None:
        _event_bus = ConversationEventBus()
    return _event_bus
