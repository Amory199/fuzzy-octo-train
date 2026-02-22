"""Tests for task priority scheduling."""

from __future__ import annotations

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.models import DAG, Task, TaskStatus, Workflow
from flowmesh.core.scheduler import Scheduler


class TestTaskPriority:
    """Verify that the scheduler dispatches higher-priority tasks first."""

    def test_ready_tasks_sorted_by_priority(self) -> None:
        """When multiple tasks are ready, higher priority comes first."""

        async def noop() -> None:
            pass

        dag = DAG()
        dag.add_node("low")
        dag.add_node("high")
        dag.add_node("medium")

        tasks = {
            "low": Task(name="low", func=noop, priority=1),
            "high": Task(name="high", func=noop, priority=10),
            "medium": Task(name="medium", func=noop, priority=5),
        }

        scheduler = Scheduler()
        ready = scheduler.get_ready_tasks(dag, tasks)

        assert [t.name for t in ready] == ["high", "medium", "low"]

    def test_priority_default_zero(self) -> None:
        """Tasks default to priority 0."""

        async def noop() -> None:
            pass

        task = Task(name="t", func=noop)
        assert task.priority == 0

    async def test_priority_affects_execution_order(self) -> None:
        """In a workflow with independent tasks, higher-priority tasks start first."""
        execution_order: list[str] = []

        async def track(name: str) -> str:
            execution_order.append(name)
            return name

        async def low() -> str:
            return await track("low")

        async def high() -> str:
            return await track("high")

        async def medium() -> str:
            return await track("medium")

        wf = Workflow(
            name="priority-test",
            tasks=[
                Task(name="low", func=low, priority=1),
                Task(name="high", func=high, priority=10),
                Task(name="medium", func=medium, priority=5),
            ],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)

        # All should succeed
        for r in results.values():
            assert r.status == TaskStatus.SUCCESS

        # High-priority task should start first
        assert execution_order[0] == "high"

    def test_priority_within_phase_in_dry_run(self) -> None:
        """Dry-run phases list higher-priority tasks first."""

        async def noop() -> None:
            pass

        wf = Workflow(
            name="priority-dry",
            tasks=[
                Task(name="low", func=noop, priority=0),
                Task(name="high", func=noop, priority=10),
                Task(name="medium", func=noop, priority=5),
            ],
        )

        plan = ExecutionEngine().dry_run(wf)
        # All tasks in one phase, ordered by priority
        assert plan.phases == [["high", "medium", "low"]]
