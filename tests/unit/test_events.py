"""Unit tests for the event bus."""

from __future__ import annotations

import pytest

from flowmesh.core.events import Event, EventBus, EventType


class TestEventBus:
    @pytest.mark.asyncio
    async def test_publish_delivers_to_subscribers(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.TASK_STARTED, handler)
        event = Event(EventType.TASK_STARTED, {"task": "a"})
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].payload["task"] == "a"

    @pytest.mark.asyncio
    async def test_no_cross_delivery(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.TASK_STARTED, handler)
        await bus.publish(Event(EventType.TASK_COMPLETED))

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_unsubscribe(self) -> None:
        bus = EventBus()
        received: list[Event] = []

        async def handler(event: Event) -> None:
            received.append(event)

        bus.subscribe(EventType.TASK_STARTED, handler)
        bus.unsubscribe(EventType.TASK_STARTED, handler)
        await bus.publish(Event(EventType.TASK_STARTED))

        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_failing_subscriber_does_not_block_others(self) -> None:
        bus = EventBus()
        ok_received: list[Event] = []

        async def bad_handler(_event: Event) -> None:
            raise RuntimeError("subscriber crash")

        async def ok_handler(event: Event) -> None:
            ok_received.append(event)

        bus.subscribe(EventType.TASK_STARTED, bad_handler)
        bus.subscribe(EventType.TASK_STARTED, ok_handler)
        await bus.publish(Event(EventType.TASK_STARTED))

        assert len(ok_received) == 1
