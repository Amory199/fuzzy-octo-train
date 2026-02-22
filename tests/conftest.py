"""Shared test fixtures."""

from __future__ import annotations

import pytest

from flowmesh.core.events import EventBus
from flowmesh.storage.memory import InMemoryWorkflowStore


@pytest.fixture()
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture()
def store() -> InMemoryWorkflowStore:
    return InMemoryWorkflowStore()
