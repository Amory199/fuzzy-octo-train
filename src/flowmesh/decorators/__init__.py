"""Decorators and utilities for easy workflow definition.

Provides a decorator-based API for defining tasks and workflows.

Example:
    from flowmesh.decorators import workflow, task

    @task(timeout=30.0, retry_count=3)
    async def extract():
        return {"records": 1000}

    @task(depends_on=["extract"])
    async def transform(*, data):
        return [r.upper() for r in data]

    @workflow(name="ETL Pipeline")
    def create_pipeline():
        return [extract, transform]

    # Execute
    pipeline = create_pipeline()
    engine = ExecutionEngine()
    results = await engine.execute(pipeline)
"""

from __future__ import annotations

import functools
from typing import TYPE_CHECKING, Any

from flowmesh.core.models import Task, Workflow

if TYPE_CHECKING:
    from collections.abc import Callable


class TaskBuilder:
    """Builder for creating Task objects with decorator syntax."""

    def __init__(
        self,
        func: Callable[..., Any],
        depends_on: list[str] | None = None,
        timeout: float = 300.0,
        retry_count: int = 0,
        priority: int = 0,
        metadata: dict[str, str] | None = None,
        input_map: dict[str, str] | None = None,
        condition: Callable[..., bool] | None = None,
    ) -> None:
        self.func = func
        self.name = func.__name__
        self.depends_on = depends_on or []
        self.timeout = timeout
        self.retry_count = retry_count
        self.priority = priority
        self.metadata = metadata or {}
        self.input_map = input_map or {}
        self.condition = condition

    def build(self) -> Task:
        """Build and return Task object."""
        return Task(
            name=self.name,
            func=self.func,
            depends_on=self.depends_on,
            timeout_seconds=self.timeout,
            retry_count=self.retry_count,
            priority=self.priority,
            metadata=self.metadata,
            input_map=self.input_map,
            condition=self.condition,
        )


def task(
    depends_on: list[str] | None = None,
    timeout: float = 300.0,
    retry_count: int = 0,
    priority: int = 0,
    metadata: dict[str, str] | None = None,
    input_map: dict[str, str] | None = None,
    condition: Callable[..., bool] | None = None,
) -> Callable[[Callable[..., Any]], TaskBuilder]:
    """Decorator for defining workflow tasks.

    Args:
        depends_on: List of task names this task depends on
        timeout: Maximum execution time in seconds
        retry_count: Number of retry attempts on failure
        priority: Task priority (higher = executed first)
        metadata: Additional metadata for the task
        input_map: Map of upstream task outputs to this task's kwargs
        condition: Callable to determine if task should execute

    Returns:
        Decorated function wrapped as TaskBuilder

    Example:
        @task(depends_on=["extract"], timeout=30.0, retry_count=3)
        async def transform(*, data):
            return [r.upper() for r in data]
    """

    def decorator(func: Callable[..., Any]) -> TaskBuilder:
        return TaskBuilder(
            func=func,
            depends_on=depends_on,
            timeout=timeout,
            retry_count=retry_count,
            priority=priority,
            metadata=metadata,
            input_map=input_map,
            condition=condition,
        )

    return decorator


def workflow(
    name: str, metadata: dict[str, str] | None = None
) -> Callable[[Callable[..., list[TaskBuilder]]], Callable[..., Workflow]]:
    """Decorator for defining workflows.

    Args:
        name: Workflow name
        metadata: Additional metadata for the workflow

    Returns:
        Decorated function that returns a Workflow object

    Example:
        @workflow(name="ETL Pipeline", metadata={"owner": "data-team"})
        def create_pipeline():
            return [extract, transform, load]

        pipeline = create_pipeline()
    """

    def decorator(func: Callable[..., list[TaskBuilder]]) -> Callable[..., Workflow]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Workflow:
            # Get task builders from the function
            task_builders = func(*args, **kwargs)

            # Build Task objects
            tasks = [tb.build() for tb in task_builders]

            # Create and return Workflow
            return Workflow(name=name, tasks=tasks, metadata=metadata or {})

        return wrapper

    return decorator


class WorkflowBuilder:
    """Fluent API for building workflows programmatically.

    Example:
        builder = WorkflowBuilder("ETL Pipeline")
        builder.add_task(extract, timeout=30.0, retry_count=3)
        builder.add_task(transform, depends_on=["extract"])
        builder.add_task(load, depends_on=["transform"])

        workflow = builder.build()
    """

    def __init__(self, name: str, metadata: dict[str, str] | None = None) -> None:
        self.name = name
        self.metadata = metadata or {}
        self._tasks: list[Task] = []

    def add_task(
        self,
        func: Callable[..., Any],
        name: str | None = None,
        depends_on: list[str] | None = None,
        timeout: float = 300.0,
        retry_count: int = 0,
        priority: int = 0,
        metadata: dict[str, str] | None = None,
        input_map: dict[str, str] | None = None,
        condition: Callable[..., bool] | None = None,
    ) -> WorkflowBuilder:
        """Add a task to the workflow.

        Args:
            func: Async callable to execute
            name: Task name (defaults to function name)
            depends_on: List of task names this task depends on
            timeout: Maximum execution time in seconds
            retry_count: Number of retry attempts on failure
            priority: Task priority (higher = executed first)
            metadata: Additional metadata for the task
            input_map: Map of upstream task outputs to this task's kwargs
            condition: Callable to determine if task should execute

        Returns:
            Self for method chaining
        """
        task = Task(
            name=name or func.__name__,
            func=func,
            depends_on=depends_on or [],
            timeout_seconds=timeout,
            retry_count=retry_count,
            priority=priority,
            metadata=metadata or {},
            input_map=input_map or {},
            condition=condition,
        )

        self._tasks.append(task)
        return self

    def build(self) -> Workflow:
        """Build and return the Workflow object.

        Returns:
            Complete Workflow ready for execution
        """
        return Workflow(name=self.name, tasks=self._tasks, metadata=self.metadata)


# Convenience function for quick workflow creation
def create_workflow(
    name: str,
    tasks: list[tuple[Callable[..., Any], dict[str, Any]]],
    metadata: dict[str, str] | None = None,
) -> Workflow:
    """Create a workflow from a list of (function, config) tuples.

    Args:
        name: Workflow name
        tasks: List of (func, config_dict) tuples
        metadata: Workflow metadata

    Returns:
        Complete Workflow object

    Example:
        workflow = create_workflow(
            name="ETL Pipeline",
            tasks=[
                (extract, {"timeout": 30.0, "retry_count": 3}),
                (transform, {"depends_on": ["extract"]}),
                (load, {"depends_on": ["transform"], "timeout": 60.0}),
            ],
        )
    """
    builder = WorkflowBuilder(name, metadata)

    for func, config in tasks:
        builder.add_task(func, **config)

    return builder.build()
