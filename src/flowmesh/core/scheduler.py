"""Task scheduler with dependency resolution and concurrency control.

The scheduler coordinates which tasks are eligible to run at any point,
respects the DAG ordering, and limits the number of concurrently
executing tasks.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from flowmesh.core.models import DAG, Task, TaskStatus

logger = logging.getLogger(__name__)


@dataclass
class SchedulerConfig:
    """Tuning knobs for the scheduler."""

    max_concurrency: int = 10
    poll_interval_seconds: float = 0.05


class Scheduler:
    """Resolves task readiness from a DAG and dispatches execution.

    The scheduler maintains a semaphore to cap concurrency and
    continuously polls for newly ready tasks as dependencies complete.
    """

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self._config = config or SchedulerConfig()
        self._semaphore = asyncio.Semaphore(self._config.max_concurrency)
        self._completed: set[str] = set()
        self._failed: set[str] = set()
        self._running: set[str] = set()

    def reset(self) -> None:
        """Clear internal bookkeeping for a fresh run."""
        self._completed.clear()
        self._failed.clear()
        self._running.clear()

    def mark_completed(self, task_name: str) -> None:
        self._completed.add(task_name)
        self._running.discard(task_name)

    def mark_failed(self, task_name: str) -> None:
        self._failed.add(task_name)
        self._running.discard(task_name)

    def mark_running(self, task_name: str) -> None:
        self._running.add(task_name)

    def get_ready_tasks(self, dag: DAG, tasks: dict[str, Task]) -> list[Task]:
        """Return tasks whose dependencies are satisfied and that are not yet scheduled."""
        ready_names = dag.get_ready_nodes(self._completed)
        result: list[Task] = []
        for name in ready_names:
            if name in self._running or name in self._failed:
                continue
            task = tasks.get(name)
            if task and task.status == TaskStatus.PENDING:
                result.append(task)
        return result

    @property
    def is_complete(self) -> bool:
        """True when there are no more tasks running."""
        return len(self._running) == 0

    @property
    def has_failures(self) -> bool:
        return len(self._failed) > 0

    @property
    def completed_count(self) -> int:
        return len(self._completed)

    @property
    def semaphore(self) -> asyncio.Semaphore:
        return self._semaphore
