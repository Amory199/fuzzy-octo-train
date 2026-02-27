"""In-memory implementation of :class:`WorkflowStore`.

Suitable for development, testing, and single-process deployments.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

from flowmesh.storage.base import WorkflowStore

if TYPE_CHECKING:
    from flowmesh.core.models import TaskResult, Workflow, WorkflowStatus


class InMemoryWorkflowStore(WorkflowStore):
    """Dictionary-backed workflow store."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}
        self._results: dict[str, dict[str, TaskResult]] = {}

    async def save(self, workflow: Workflow) -> None:
        self._workflows[workflow.id] = copy.deepcopy(workflow)

    async def get(self, workflow_id: str) -> Workflow | None:
        wf = self._workflows.get(workflow_id)
        return copy.deepcopy(wf) if wf else None

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Workflow]:
        all_wf = list(self._workflows.values())
        return [copy.deepcopy(w) for w in all_wf[offset : offset + limit]]

    async def update_status(self, workflow_id: str, status: WorkflowStatus) -> None:
        wf = self._workflows.get(workflow_id)
        if wf:
            wf.status = status

    async def save_results(self, workflow_id: str, results: dict[str, TaskResult]) -> None:
        self._results[workflow_id] = copy.deepcopy(results)

    async def get_results(self, workflow_id: str) -> dict[str, TaskResult] | None:
        res = self._results.get(workflow_id)
        return copy.deepcopy(res) if res else None
