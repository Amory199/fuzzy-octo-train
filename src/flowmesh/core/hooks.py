"""Execution hooks — middleware for task lifecycle.

Hooks let you inject cross-cutting logic (logging, metrics, validation,
caching) that runs before and/or after every task without modifying
the task functions themselves.

Usage::

    class MetricsHook(TaskHook):
        async def before_task(self, task, workflow):
            print(f"Starting {task.name}")

        async def after_task(self, task, result, workflow):
            print(f"{task.name} took {result.duration_ms}ms")

    engine = ExecutionEngine(hooks=[MetricsHook()])
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flowmesh.core.models import Task, TaskResult, Workflow


class TaskHook:
    """Base class for task execution hooks.

    Override :meth:`before_task` and/or :meth:`after_task` to add
    behaviour.  Both methods are no-ops by default so you only need
    to implement the ones you care about.
    """

    async def before_task(self, task: Task, workflow: Workflow) -> None:
        """Called just before a task is executed.

        Raising an exception here will prevent the task from running
        and mark it as failed.
        """

    async def after_task(self, task: Task, result: TaskResult, workflow: Workflow) -> None:
        """Called after a task completes (success **or** failure)."""
