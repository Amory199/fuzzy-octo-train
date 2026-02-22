"""Tests for task data-flow (output passing between tasks)."""

from __future__ import annotations

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.models import Task, TaskStatus, Workflow


class TestDataFlow:
    """Verify that upstream task outputs are injected into downstream tasks."""

    async def test_simple_data_flow(self) -> None:
        """Output of 'produce' flows into 'consume' via input_map."""

        async def produce() -> dict[str, int]:
            return {"value": 42}

        async def consume(*, data: dict[str, int]) -> str:
            return f"received {data['value']}"

        wf = Workflow(
            name="data-flow",
            tasks=[
                Task(name="produce", func=produce),
                Task(
                    name="consume",
                    func=consume,
                    depends_on=["produce"],
                    input_map={"data": "produce"},
                ),
            ],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["produce"].status == TaskStatus.SUCCESS
        assert results["produce"].output == {"value": 42}
        assert results["consume"].status == TaskStatus.SUCCESS
        assert results["consume"].output == "received 42"

    async def test_multi_input_data_flow(self) -> None:
        """A task can receive outputs from multiple upstream tasks."""

        async def fetch_users() -> list[str]:
            return ["alice", "bob"]

        async def fetch_scores() -> dict[str, int]:
            return {"alice": 90, "bob": 85}

        async def merge(*, users: list[str], scores: dict[str, int]) -> dict[str, int]:
            return {u: scores[u] for u in users}

        wf = Workflow(
            name="multi-input",
            tasks=[
                Task(name="fetch_users", func=fetch_users),
                Task(name="fetch_scores", func=fetch_scores),
                Task(
                    name="merge",
                    func=merge,
                    depends_on=["fetch_users", "fetch_scores"],
                    input_map={"users": "fetch_users", "scores": "fetch_scores"},
                ),
            ],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["merge"].output == {"alice": 90, "bob": 85}

    async def test_data_flow_chain(self) -> None:
        """Data flows through a chain: a → b → c."""

        async def step_a() -> int:
            return 10

        async def step_b(*, val: int) -> int:
            return val * 2

        async def step_c(*, val: int) -> int:
            return val + 1

        wf = Workflow(
            name="chain",
            tasks=[
                Task(name="a", func=step_a),
                Task(name="b", func=step_b, depends_on=["a"], input_map={"val": "a"}),
                Task(name="c", func=step_c, depends_on=["b"], input_map={"val": "b"}),
            ],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["a"].output == 10
        assert results["b"].output == 20
        assert results["c"].output == 21

    async def test_no_input_map_backward_compat(self) -> None:
        """Tasks without input_map still work exactly as before."""

        async def noop() -> str:
            return "ok"

        wf = Workflow(
            name="compat",
            tasks=[Task(name="t1", func=noop)],
        )

        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["t1"].output == "ok"
