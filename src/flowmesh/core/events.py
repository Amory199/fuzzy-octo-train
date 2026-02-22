"""Async event bus for decoupled communication between components.

Implements a publish/subscribe pattern that allows the engine, API layer,
and storage backends to react to lifecycle events without tight coupling.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections import defaultdict
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class EventType(Enum):
    """Predefined lifecycle events emitted by the engine."""

    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    TASK_STARTED = "task.started"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_RETRYING = "task.retrying"
    TASK_SKIPPED = "task.skipped"


@dataclass(frozen=True)
class Event:
    """An immutable event carrying contextual payload."""

    event_type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))


# Subscriber callable type
Subscriber = Callable[[Event], Coroutine[Any, Any, None]]


class EventBus:
    """In-process async event bus.

    Subscribers are invoked concurrently via :func:`asyncio.gather` when
    an event is published.  A failing subscriber does **not** prevent
    other subscribers from executing.
    """

    def __init__(self) -> None:
        self._subscribers: dict[EventType, list[Subscriber]] = defaultdict(list)

    def subscribe(self, event_type: EventType, handler: Subscriber) -> None:
        """Register *handler* for *event_type*."""
        self._subscribers[event_type].append(handler)

    def unsubscribe(self, event_type: EventType, handler: Subscriber) -> None:
        """Remove a previously registered handler."""
        with contextlib.suppress(ValueError):
            self._subscribers[event_type].remove(handler)

    async def publish(self, event: Event) -> None:
        """Dispatch *event* to all matching subscribers concurrently."""
        handlers = self._subscribers.get(event.event_type, [])
        if not handlers:
            return

        results = await asyncio.gather(*(h(event) for h in handlers), return_exceptions=True)
        for idx, result in enumerate(results):
            if isinstance(result, BaseException):
                logger.error(
                    "Subscriber %s raised %s for event %s",
                    handlers[idx].__qualname__,
                    result,
                    event.event_type.value,
                )
