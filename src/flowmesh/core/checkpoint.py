"""Workflow checkpointing for resumable execution.

Allows persisting completed-task results after each task finishes so
that a failed workflow can be resumed from the last successful point
instead of re-running everything from scratch.
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flowmesh.core.models import TaskResult


class CheckpointStore(ABC):
    """Abstract interface for persisting workflow checkpoints."""

    @abstractmethod
    async def save_task_result(self, workflow_id: str, task_name: str, result: TaskResult) -> None:
        """Persist the result of a single completed task."""
        ...

    @abstractmethod
    async def load_checkpoint(self, workflow_id: str) -> dict[str, TaskResult] | None:
        """Return all saved task results for a workflow, or ``None``."""
        ...

    @abstractmethod
    async def clear(self, workflow_id: str) -> None:
        """Remove the checkpoint for a workflow."""
        ...


class InMemoryCheckpointStore(CheckpointStore):
    """Dictionary-backed checkpoint store for development and testing."""

    def __init__(self) -> None:
        self._data: dict[str, dict[str, TaskResult]] = {}

    async def save_task_result(self, workflow_id: str, task_name: str, result: TaskResult) -> None:
        if workflow_id not in self._data:
            self._data[workflow_id] = {}
        self._data[workflow_id][task_name] = copy.deepcopy(result)

    async def load_checkpoint(self, workflow_id: str) -> dict[str, TaskResult] | None:
        cp = self._data.get(workflow_id)
        return copy.deepcopy(cp) if cp else None

    async def clear(self, workflow_id: str) -> None:
        self._data.pop(workflow_id, None)
