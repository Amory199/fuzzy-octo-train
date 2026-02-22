"""Tests for dry-run / execution plan."""

from __future__ import annotations

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.models import Task, Workflow


class TestDryRun:
    """Verify that dry_run produces correct execution plans."""

    def test_linear_pipeline(self) -> None:
        """Linear A → B → C produces three single-task phases."""

        async def noop() -> None:
            pass

        wf = Workflow(
            name="linear",
            tasks=[
                Task(name="a", func=noop),
                Task(name="b", func=noop, depends_on=["a"]),
                Task(name="c", func=noop, depends_on=["b"]),
            ],
        )

        plan = ExecutionEngine().dry_run(wf)

        assert plan.total_tasks == 3
        assert plan.phases == [["a"], ["b"], ["c"]]
        assert plan.critical_path == ["a", "b", "c"]
        assert plan.critical_path_length == 3

    def test_diamond_dependency(self) -> None:
        """Diamond: A → (B, C) → D produces three phases with B+C in parallel."""

        async def noop() -> None:
            pass

        wf = Workflow(
            name="diamond",
            tasks=[
                Task(name="a", func=noop),
                Task(name="b", func=noop, depends_on=["a"]),
                Task(name="c", func=noop, depends_on=["a"]),
                Task(name="d", func=noop, depends_on=["b", "c"]),
            ],
        )

        plan = ExecutionEngine().dry_run(wf)

        assert plan.total_tasks == 4
        assert len(plan.phases) == 3
        assert plan.phases[0] == ["a"]
        assert set(plan.phases[1]) == {"b", "c"}
        assert plan.phases[2] == ["d"]
        # Critical path is length 3 (a → b → d or a → c → d)
        assert plan.critical_path_length == 3
        assert plan.critical_path[0] == "a"
        assert plan.critical_path[-1] == "d"

    def test_all_independent(self) -> None:
        """All independent tasks form a single phase."""

        async def noop() -> None:
            pass

        wf = Workflow(
            name="parallel",
            tasks=[
                Task(name="a", func=noop),
                Task(name="b", func=noop),
                Task(name="c", func=noop),
            ],
        )

        plan = ExecutionEngine().dry_run(wf)

        assert plan.total_tasks == 3
        assert len(plan.phases) == 1
        assert set(plan.phases[0]) == {"a", "b", "c"}
        assert plan.critical_path_length == 1

    def test_single_task(self) -> None:
        """Single task produces one phase with one task."""

        async def noop() -> None:
            pass

        wf = Workflow(name="single", tasks=[Task(name="only", func=noop)])

        plan = ExecutionEngine().dry_run(wf)

        assert plan.total_tasks == 1
        assert plan.phases == [["only"]]
        assert plan.critical_path == ["only"]
        assert plan.critical_path_length == 1

    def test_wide_fan_out(self) -> None:
        """Fan-out: root → (a, b, c, d, e) → sink."""

        async def noop() -> None:
            pass

        wf = Workflow(
            name="fan-out",
            tasks=[
                Task(name="root", func=noop),
                *[Task(name=f"t{i}", func=noop, depends_on=["root"]) for i in range(5)],
                Task(
                    name="sink",
                    func=noop,
                    depends_on=[f"t{i}" for i in range(5)],
                ),
            ],
        )

        plan = ExecutionEngine().dry_run(wf)

        assert plan.total_tasks == 7
        assert len(plan.phases) == 3
        assert plan.phases[0] == ["root"]
        assert set(plan.phases[1]) == {f"t{i}" for i in range(5)}
        assert plan.phases[2] == ["sink"]
        assert plan.critical_path_length == 3

    def test_execution_plan_is_frozen(self) -> None:
        """ExecutionPlan is immutable (frozen dataclass)."""

        async def noop() -> None:
            pass

        import pytest

        wf = Workflow(name="frozen", tasks=[Task(name="a", func=noop)])
        plan = ExecutionEngine().dry_run(wf)

        # Frozen dataclass should raise on attribute assignment
        with pytest.raises(AttributeError):
            plan.total_tasks = 999  # type: ignore[misc]
