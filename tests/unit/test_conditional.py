"""Tests for conditional task execution."""

from __future__ import annotations

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.events import EventBus, EventType
from flowmesh.core.models import Task, TaskStatus, Workflow


class TestConditionalExecution:
    """Verify that tasks with conditions are skipped or executed correctly."""

    async def test_condition_true_executes(self) -> None:
        """When condition returns True the task runs normally."""

        async def produce() -> int:
            return 100

        async def consume(*, val: int) -> int:
            return val + 1

        wf = Workflow(
            name="cond-true",
            tasks=[
                Task(name="produce", func=produce),
                Task(
                    name="consume",
                    func=consume,
                    depends_on=["produce"],
                    input_map={"val": "produce"},
                    condition=lambda upstream: upstream["produce"].output > 50,
                ),
            ],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["consume"].status == TaskStatus.SUCCESS
        assert results["consume"].output == 101

    async def test_condition_false_skips(self) -> None:
        """When condition returns False the task is skipped."""

        async def produce() -> int:
            return 10

        async def consume(*, val: int) -> int:
            return val + 1

        wf = Workflow(
            name="cond-false",
            tasks=[
                Task(name="produce", func=produce),
                Task(
                    name="consume",
                    func=consume,
                    depends_on=["produce"],
                    input_map={"val": "produce"},
                    condition=lambda upstream: upstream["produce"].output > 50,
                ),
            ],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["consume"].status == TaskStatus.SKIPPED

    async def test_skipped_task_satisfies_downstream(self) -> None:
        """A skipped task still unblocks downstream dependents."""

        async def start() -> str:
            return "go"

        async def maybe_skip() -> str:
            return "should be skipped"

        async def final() -> str:
            return "done"

        wf = Workflow(
            name="skip-chain",
            tasks=[
                Task(name="start", func=start),
                Task(
                    name="maybe_skip",
                    func=maybe_skip,
                    depends_on=["start"],
                    condition=lambda _upstream: False,  # always skip
                ),
                Task(name="final", func=final, depends_on=["maybe_skip"]),
            ],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["maybe_skip"].status == TaskStatus.SKIPPED
        assert results["final"].status == TaskStatus.SUCCESS
        assert results["final"].output == "done"

    async def test_skip_emits_event(self) -> None:
        """TASK_SKIPPED event is published when a task is skipped."""
        skipped_events: list[str] = []
        bus = EventBus()

        async def on_skip(event: object) -> None:
            skipped_events.append(event.payload["task_name"])  # type: ignore[union-attr]

        bus.subscribe(EventType.TASK_SKIPPED, on_skip)

        async def produce() -> int:
            return 1

        async def consume() -> None:
            pass

        wf = Workflow(
            name="skip-event",
            tasks=[
                Task(name="produce", func=produce),
                Task(
                    name="consume",
                    func=consume,
                    depends_on=["produce"],
                    condition=lambda _: False,
                ),
            ],
        )

        engine = ExecutionEngine(event_bus=bus)
        await engine.execute(wf)

        assert skipped_events == ["consume"]

    async def test_no_condition_backward_compat(self) -> None:
        """Tasks without condition still execute normally."""

        async def noop() -> str:
            return "ok"

        wf = Workflow(
            name="no-cond",
            tasks=[Task(name="t", func=noop)],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)
        assert results["t"].status == TaskStatus.SUCCESS
