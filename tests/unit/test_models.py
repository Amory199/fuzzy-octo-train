"""Unit tests for core domain models — Task, Workflow, DAG."""

from __future__ import annotations

from datetime import UTC

import pytest

from flowmesh.core.models import (
    DAG,
    CycleDetectedError,
    Task,
    TaskResult,
    TaskStatus,
    Workflow,
)

# ── DAG ──────────────────────────────────────────────────────────────


class TestDAG:
    def test_topological_sort_linear(self) -> None:
        dag = DAG()
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        order = dag.topological_sort()
        assert order.index("a") < order.index("b") < order.index("c")

    def test_topological_sort_diamond(self) -> None:
        dag = DAG()
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        dag.add_edge("b", "d")
        dag.add_edge("c", "d")
        order = dag.topological_sort()
        assert order.index("a") < order.index("b")
        assert order.index("a") < order.index("c")
        assert order.index("b") < order.index("d")
        assert order.index("c") < order.index("d")

    def test_cycle_detected(self) -> None:
        dag = DAG()
        dag.add_edge("a", "b")
        dag.add_edge("b", "c")
        dag.add_edge("c", "a")
        with pytest.raises(CycleDetectedError):
            dag.topological_sort()

    def test_single_node(self) -> None:
        dag = DAG()
        dag.add_node("solo")
        assert dag.topological_sort() == ["solo"]

    def test_get_ready_nodes(self) -> None:
        dag = DAG()
        dag.add_edge("a", "b")
        dag.add_edge("a", "c")
        assert set(dag.get_ready_nodes(set())) == {"a"}
        assert set(dag.get_ready_nodes({"a"})) == {"b", "c"}

    def test_nodes_property(self) -> None:
        dag = DAG()
        dag.add_edge("x", "y")
        assert dag.nodes == {"x", "y"}


# ── TaskResult ───────────────────────────────────────────────────────


class TestTaskResult:
    def test_duration_calculation(self) -> None:
        from datetime import datetime

        start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        end = datetime(2025, 1, 1, 0, 0, 1, 500_000, tzinfo=UTC)
        result = TaskResult(
            task_id="t1", status=TaskStatus.SUCCESS, started_at=start, finished_at=end
        )
        assert result.duration_ms is not None
        assert abs(result.duration_ms - 1500.0) < 1.0

    def test_duration_none_when_incomplete(self) -> None:
        result = TaskResult(task_id="t1", status=TaskStatus.RUNNING)
        assert result.duration_ms is None


# ── Workflow ─────────────────────────────────────────────────────────


class TestWorkflow:
    @staticmethod
    async def _noop() -> str:
        return "ok"

    def test_build_dag_valid(self) -> None:
        wf = Workflow(
            name="test",
            tasks=[
                Task(name="a", func=TestWorkflow._noop),
                Task(name="b", func=TestWorkflow._noop, depends_on=["a"]),
            ],
        )
        dag = wf.build_dag()
        order = dag.topological_sort()
        assert order.index("a") < order.index("b")

    def test_build_dag_cycle(self) -> None:
        wf = Workflow(
            name="cycle",
            tasks=[
                Task(name="a", func=TestWorkflow._noop, depends_on=["b"]),
                Task(name="b", func=TestWorkflow._noop, depends_on=["a"]),
            ],
        )
        with pytest.raises(CycleDetectedError):
            wf.build_dag()

    def test_unknown_dependency(self) -> None:
        wf = Workflow(
            name="bad",
            tasks=[
                Task(name="a", func=TestWorkflow._noop, depends_on=["nonexistent"]),
            ],
        )
        with pytest.raises(ValueError, match="unknown task"):
            wf.build_dag()

    def test_get_task_by_name(self) -> None:
        task_a = Task(name="a", func=TestWorkflow._noop)
        wf = Workflow(name="w", tasks=[task_a])
        assert wf.get_task_by_name("a") is task_a
        assert wf.get_task_by_name("missing") is None
