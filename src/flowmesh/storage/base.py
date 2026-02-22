"""Abstract storage interface (ports-and-adapters / hexagonal pattern).

Any persistence backend (memory, Redis, Postgres, …) must implement
this protocol so the engine and API remain decoupled from storage details.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flowmesh.core.models import TaskResult, Workflow, WorkflowStatus


class WorkflowStore(ABC):
    """Abstract repository for workflow persistence."""

    @abstractmethod
    async def save(self, workflow: Workflow) -> None: ...

    @abstractmethod
    async def get(self, workflow_id: str) -> Workflow | None: ...

    @abstractmethod
    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Workflow]: ...

    @abstractmethod
    async def update_status(self, workflow_id: str, status: WorkflowStatus) -> None: ...

    @abstractmethod
    async def save_results(
        self, workflow_id: str, results: dict[str, TaskResult]
    ) -> None: ...

    @abstractmethod
    async def get_results(self, workflow_id: str) -> dict[str, TaskResult] | None: ...
