"""Workflow execution engine — the central orchestrator.

Ties together the DAG, scheduler, event bus, and resilience patterns
to execute a full workflow asynchronously.

Supports three advanced features:

* **Data flow** — upstream task outputs are automatically injected as
  keyword arguments to downstream tasks via :attr:`Task.input_map`.
* **Conditional execution** — tasks may declare a :attr:`Task.condition`
  callable; when it returns ``False`` the task is skipped.
* **Checkpointing & resume** — when a :class:`CheckpointStore` is
  provided, the engine persists each completed task and can resume a
  previously-failed workflow from the last successful point.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from flowmesh.core.events import Event, EventBus, EventType
from flowmesh.core.models import (
    Task,
    TaskResult,
    TaskStatus,
    Workflow,
    WorkflowStatus,
)
from flowmesh.core.scheduler import Scheduler, SchedulerConfig
from flowmesh.patterns.circuit_breaker import CircuitBreaker, CircuitOpenError
from flowmesh.patterns.retry import RetryPolicy, retry_with_backoff

if TYPE_CHECKING:
    from flowmesh.core.checkpoint import CheckpointStore

logger = logging.getLogger(__name__)


class ExecutionEngine:
    """Runs a :class:`Workflow` respecting dependency order and concurrency.

    The engine:
    1. Builds and validates the workflow DAG.
    2. Iteratively discovers ready tasks via the :class:`Scheduler`.
    3. Evaluates optional *conditions* and skips tasks whose conditions
       return ``False``.
    4. Injects upstream outputs into downstream tasks via *input_map*.
    5. Executes each task behind an optional :class:`CircuitBreaker` and
       :class:`RetryPolicy`.
    6. Publishes lifecycle events through the :class:`EventBus`.
    7. Optionally checkpoints after each task for resumable execution.
    """

    def __init__(
        self,
        event_bus: EventBus | None = None,
        scheduler_config: SchedulerConfig | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        default_retry: RetryPolicy | None = None,
        checkpoint_store: CheckpointStore | None = None,
    ) -> None:
        self._event_bus = event_bus or EventBus()
        self._scheduler = Scheduler(scheduler_config)
        self._circuit_breaker = circuit_breaker
        self._default_retry = default_retry or RetryPolicy(max_retries=0)
        self._checkpoint_store = checkpoint_store

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    async def execute(self, workflow: Workflow) -> dict[str, TaskResult]:
        """Execute *workflow* and return a mapping of task name → result."""
        dag = workflow.build_dag()
        self._scheduler.reset()
        task_map: dict[str, Task] = {t.name: t for t in workflow.tasks}
        results: dict[str, TaskResult] = {}

        workflow.status = WorkflowStatus.RUNNING
        await self._event_bus.publish(
            Event(EventType.WORKFLOW_STARTED, {"workflow_id": workflow.id, "name": workflow.name})
        )

        try:
            await self._run_loop(dag, task_map, results, workflow)
        except Exception:
            workflow.status = WorkflowStatus.FAILED
            await self._event_bus.publish(
                Event(EventType.WORKFLOW_FAILED, {"workflow_id": workflow.id})
            )
            raise

        if self._scheduler.has_failures:
            workflow.status = WorkflowStatus.FAILED
            await self._event_bus.publish(
                Event(EventType.WORKFLOW_FAILED, {"workflow_id": workflow.id})
            )
        else:
            workflow.status = WorkflowStatus.SUCCESS
            await self._event_bus.publish(
                Event(
                    EventType.WORKFLOW_COMPLETED,
                    {"workflow_id": workflow.id, "task_count": len(results)},
                )
            )

        return results

    async def resume(self, workflow: Workflow) -> dict[str, TaskResult]:
        """Resume a previously-failed workflow from its last checkpoint.

        Already-succeeded tasks are not re-executed; the engine picks up
        where the last run left off.  Requires a :class:`CheckpointStore`
        to have been configured.
        """
        if self._checkpoint_store is None:
            raise RuntimeError("Cannot resume without a checkpoint store")

        checkpoint = await self._checkpoint_store.load_checkpoint(workflow.id)
        dag = workflow.build_dag()
        self._scheduler.reset()
        task_map: dict[str, Task] = {t.name: t for t in workflow.tasks}
        results: dict[str, TaskResult] = {}

        # Restore completed tasks from checkpoint
        if checkpoint:
            for task_name, task_result in checkpoint.items():
                if task_result.status == TaskStatus.SUCCESS:
                    results[task_name] = task_result
                    task = task_map.get(task_name)
                    if task:
                        task.status = TaskStatus.SUCCESS
                        task.result = task_result
                    self._scheduler.mark_completed(task_name)
                elif task_result.status == TaskStatus.SKIPPED:
                    results[task_name] = task_result
                    task = task_map.get(task_name)
                    if task:
                        task.status = TaskStatus.SKIPPED
                        task.result = task_result
                    self._scheduler.mark_skipped(task_name)

        workflow.status = WorkflowStatus.RUNNING
        await self._event_bus.publish(
            Event(EventType.WORKFLOW_STARTED, {"workflow_id": workflow.id, "name": workflow.name})
        )

        try:
            await self._run_loop(dag, task_map, results, workflow)
        except Exception:
            workflow.status = WorkflowStatus.FAILED
            await self._event_bus.publish(
                Event(EventType.WORKFLOW_FAILED, {"workflow_id": workflow.id})
            )
            raise

        if self._scheduler.has_failures:
            workflow.status = WorkflowStatus.FAILED
            await self._event_bus.publish(
                Event(EventType.WORKFLOW_FAILED, {"workflow_id": workflow.id})
            )
        else:
            workflow.status = WorkflowStatus.SUCCESS
            await self._event_bus.publish(
                Event(
                    EventType.WORKFLOW_COMPLETED,
                    {"workflow_id": workflow.id, "task_count": len(results)},
                )
            )
            # Clear checkpoint on successful completion
            await self._checkpoint_store.clear(workflow.id)

        return results

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_loop(
        self,
        dag: Any,
        task_map: dict[str, Task],
        results: dict[str, TaskResult],
        workflow: Workflow,
    ) -> None:
        pending_futures: set[asyncio.Task[None]] = set()

        while True:
            ready = self._scheduler.get_ready_tasks(dag, task_map)
            for task in ready:
                self._scheduler.mark_running(task.name)
                task.status = TaskStatus.RUNNING
                future = asyncio.create_task(self._execute_task(task, results, workflow))
                pending_futures.add(future)
                future.add_done_callback(pending_futures.discard)

            if not pending_futures and self._scheduler.is_complete:
                break

            if pending_futures:
                done, _ = await asyncio.wait(pending_futures, return_when=asyncio.FIRST_COMPLETED)
                for d in done:
                    # Propagate exceptions stored in done futures
                    if d.exception() is not None:
                        logger.error("Task future raised: %s", d.exception())
            else:
                await asyncio.sleep(self._scheduler._config.poll_interval_seconds)

    async def _execute_task(
        self,
        task: Task,
        results: dict[str, TaskResult],
        workflow: Workflow,
    ) -> None:
        # --- Conditional execution ---
        if task.condition is not None:
            upstream_results = {dep: results[dep] for dep in task.depends_on if dep in results}
            if not task.condition(upstream_results):
                result = TaskResult(
                    task_id=task.id,
                    status=TaskStatus.SKIPPED,
                    started_at=datetime.now(UTC),
                    finished_at=datetime.now(UTC),
                )
                task.status = TaskStatus.SKIPPED
                task.result = result
                results[task.name] = result
                self._scheduler.mark_skipped(task.name)
                await self._event_bus.publish(
                    Event(
                        EventType.TASK_SKIPPED,
                        {"workflow_id": workflow.id, "task_name": task.name},
                    )
                )
                if self._checkpoint_store:
                    await self._checkpoint_store.save_task_result(workflow.id, task.name, result)
                return

        started = datetime.now(UTC)
        await self._event_bus.publish(
            Event(
                EventType.TASK_STARTED,
                {"workflow_id": workflow.id, "task_id": task.id, "task_name": task.name},
            )
        )

        retries = task.retry_count or self._default_retry.max_retries
        policy = RetryPolicy(max_retries=retries)

        try:
            output = await self._invoke(task, policy, results)
            finished = datetime.now(UTC)
            result = TaskResult(
                task_id=task.id,
                status=TaskStatus.SUCCESS,
                output=output,
                started_at=started,
                finished_at=finished,
            )
            task.status = TaskStatus.SUCCESS
            task.result = result
            results[task.name] = result
            self._scheduler.mark_completed(task.name)
            await self._event_bus.publish(
                Event(
                    EventType.TASK_COMPLETED,
                    {
                        "workflow_id": workflow.id,
                        "task_name": task.name,
                        "duration_ms": result.duration_ms,
                    },
                )
            )
            if self._checkpoint_store:
                await self._checkpoint_store.save_task_result(workflow.id, task.name, result)
        except Exception as exc:
            finished = datetime.now(UTC)
            result = TaskResult(
                task_id=task.id,
                status=TaskStatus.FAILED,
                error=str(exc),
                started_at=started,
                finished_at=finished,
            )
            task.status = TaskStatus.FAILED
            task.result = result
            results[task.name] = result
            self._scheduler.mark_failed(task.name)
            await self._event_bus.publish(
                Event(
                    EventType.TASK_FAILED,
                    {"workflow_id": workflow.id, "task_name": task.name, "error": str(exc)},
                )
            )

    async def _invoke(self, task: Task, policy: RetryPolicy, results: dict[str, TaskResult]) -> Any:
        """Call the task function, honouring circuit-breaker, retry, and data-flow logic."""

        # Build kwargs from input_map (data flow)
        kwargs: dict[str, Any] = {}
        if task.input_map:
            for param_name, upstream_task_name in task.input_map.items():
                upstream = results.get(upstream_task_name)
                if upstream is not None:
                    kwargs[param_name] = upstream.output

        async def _call() -> Any:
            if self._circuit_breaker:
                try:
                    return await self._circuit_breaker.call(task.func, **kwargs)
                except CircuitOpenError:
                    raise
            return await asyncio.wait_for(task.func(**kwargs), timeout=task.timeout_seconds)

        return await retry_with_backoff(_call, policy)
