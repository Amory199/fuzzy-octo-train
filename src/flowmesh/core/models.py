"""Domain models for the FlowMesh orchestration engine.

Defines the core value objects and entities: Task, TaskResult, Workflow,
and the DAG (directed acyclic graph) that governs execution order.
"""

from __future__ import annotations

import enum
import uuid
from collections import deque
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


class TaskStatus(enum.Enum):
    """Lifecycle states of an individual task."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class WorkflowStatus(enum.Enum):
    """Lifecycle states of a workflow."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


# Type alias for async task callables
TaskCallable = Callable[..., Coroutine[Any, Any, Any]]


@dataclass
class TaskResult:
    """Immutable result produced by a completed task."""

    task_id: str
    status: TaskStatus
    output: Any = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None

    @property
    def duration_ms(self) -> float | None:
        """Wall-clock duration in milliseconds, or ``None`` if incomplete."""
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds() * 1000
        return None


@dataclass
class Task:
    """A unit of work inside a workflow.

    Each task wraps an async callable and may declare dependencies on
    other tasks via :attr:`depends_on`.
    """

    name: str
    func: TaskCallable
    depends_on: list[str] = field(default_factory=list)
    timeout_seconds: float = 300.0
    retry_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: TaskStatus = TaskStatus.PENDING
    result: TaskResult | None = None

    def __hash__(self) -> int:
        return hash(self.id)


class CycleDetectedError(Exception):
    """Raised when a workflow DAG contains a cycle."""


class DAG:
    """Directed acyclic graph that models task dependencies.

    Provides topological sorting via Kahn's algorithm and efficient
    queries for ready-to-run tasks.
    """

    def __init__(self) -> None:
        self._adjacency: dict[str, set[str]] = {}
        self._in_degree: dict[str, int] = {}

    def add_node(self, node_id: str) -> None:
        """Register a node (task) in the graph."""
        self._adjacency.setdefault(node_id, set())
        self._in_degree.setdefault(node_id, 0)

    def add_edge(self, from_id: str, to_id: str) -> None:
        """Declare that *from_id* must complete before *to_id* starts."""
        self.add_node(from_id)
        self.add_node(to_id)
        if to_id not in self._adjacency[from_id]:
            self._adjacency[from_id].add(to_id)
            self._in_degree[to_id] += 1

    def topological_sort(self) -> list[str]:
        """Return a valid topological ordering of all nodes.

        Raises :class:`CycleDetectedError` if the graph contains a cycle.
        """
        in_degree = dict(self._in_degree)
        queue: deque[str] = deque(n for n, d in in_degree.items() if d == 0)
        order: list[str] = []

        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbour in self._adjacency.get(node, set()):
                in_degree[neighbour] -= 1
                if in_degree[neighbour] == 0:
                    queue.append(neighbour)

        if len(order) != len(self._adjacency):
            raise CycleDetectedError(
                "Workflow contains a dependency cycle — topological sort impossible"
            )
        return order

    def get_ready_nodes(self, completed: set[str]) -> list[str]:
        """Return nodes whose dependencies are fully satisfied."""
        ready: list[str] = []
        for node_id in self._adjacency:
            if node_id in completed:
                continue
            deps = {
                src for src, targets in self._adjacency.items() if node_id in targets
            }
            if deps <= completed:
                ready.append(node_id)
        return ready

    @property
    def nodes(self) -> set[str]:
        return set(self._adjacency.keys())


@dataclass
class Workflow:
    """A named collection of tasks with declared dependencies.

    Building a workflow automatically constructs the underlying DAG and
    validates it (no cycles).
    """

    name: str
    tasks: list[Task] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    status: WorkflowStatus = WorkflowStatus.PENDING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    def build_dag(self) -> DAG:
        """Construct and validate the DAG from the current task list."""
        dag = DAG()
        task_names = {t.name for t in self.tasks}
        for task in self.tasks:
            dag.add_node(task.name)
            for dep in task.depends_on:
                if dep not in task_names:
                    raise ValueError(
                        f"Task '{task.name}' depends on unknown task '{dep}'"
                    )
                dag.add_edge(dep, task.name)
        # Validate — will raise CycleDetectedError if invalid
        dag.topological_sort()
        return dag

    def get_task_by_name(self, name: str) -> Task | None:
        """Look up a task by its human-readable name."""
        for task in self.tasks:
            if task.name == name:
                return task
        return None
