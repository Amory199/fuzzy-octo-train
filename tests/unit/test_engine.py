"""Unit tests for the workflow execution engine."""

from __future__ import annotations

import asyncio

import pytest

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.events import Event, EventBus, EventType
from flowmesh.core.models import Task, TaskStatus, Workflow, WorkflowStatus

# ── Helpers ──────────────────────────────────────────────────────────


async def _fast_task() -> str:
    await asyncio.sleep(0.01)
    return "done"


async def _failing_task() -> None:
    raise RuntimeError("boom")


# ── Tests ────────────────────────────────────────────────────────────


class TestExecutionEngine:
    @pytest.mark.asyncio
    async def test_simple_linear_workflow(self) -> None:
        wf = Workflow(
            name="linear",
            tasks=[
                Task(name="a", func=_fast_task),
                Task(name="b", func=_fast_task, depends_on=["a"]),
                Task(name="c", func=_fast_task, depends_on=["b"]),
            ],
        )
        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert len(results) == 3
        assert all(r.status == TaskStatus.SUCCESS for r in results.values())
        assert wf.status == WorkflowStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_parallel_fan_out(self) -> None:
        wf = Workflow(
            name="fan-out",
            tasks=[
                Task(name="root", func=_fast_task),
                Task(name="b1", func=_fast_task, depends_on=["root"]),
                Task(name="b2", func=_fast_task, depends_on=["root"]),
                Task(name="b3", func=_fast_task, depends_on=["root"]),
            ],
        )
        engine = ExecutionEngine()
        results = await engine.execute(wf)
        assert len(results) == 4
        assert wf.status == WorkflowStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_task_failure_marks_workflow_failed(self) -> None:
        wf = Workflow(
            name="fail",
            tasks=[
                Task(name="good", func=_fast_task),
                Task(name="bad", func=_failing_task, depends_on=["good"]),
            ],
        )
        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["bad"].status == TaskStatus.FAILED
        assert wf.status == WorkflowStatus.FAILED
        assert "boom" in (results["bad"].error or "")

    @pytest.mark.asyncio
    async def test_events_are_published(self) -> None:
        bus = EventBus()
        events_received: list[Event] = []

        async def _capture(event: Event) -> None:
            events_received.append(event)

        bus.subscribe(EventType.WORKFLOW_STARTED, _capture)
        bus.subscribe(EventType.WORKFLOW_COMPLETED, _capture)
        bus.subscribe(EventType.TASK_STARTED, _capture)
        bus.subscribe(EventType.TASK_COMPLETED, _capture)

        wf = Workflow(
            name="evented",
            tasks=[Task(name="only", func=_fast_task)],
        )
        engine = ExecutionEngine(event_bus=bus)
        await engine.execute(wf)

        event_types = [e.event_type for e in events_received]
        assert EventType.WORKFLOW_STARTED in event_types
        assert EventType.WORKFLOW_COMPLETED in event_types
        assert EventType.TASK_STARTED in event_types
        assert EventType.TASK_COMPLETED in event_types

    @pytest.mark.asyncio
    async def test_diamond_dependency(self) -> None:
        wf = Workflow(
            name="diamond",
            tasks=[
                Task(name="a", func=_fast_task),
                Task(name="b", func=_fast_task, depends_on=["a"]),
                Task(name="c", func=_fast_task, depends_on=["a"]),
                Task(name="d", func=_fast_task, depends_on=["b", "c"]),
            ],
        )
        engine = ExecutionEngine()
        results = await engine.execute(wf)
        assert len(results) == 4
        assert wf.status == WorkflowStatus.SUCCESS
