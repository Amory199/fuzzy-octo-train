"""Unit tests for the task scheduler."""

from __future__ import annotations

from flowmesh.core.models import DAG, Task, TaskStatus
from flowmesh.core.scheduler import Scheduler


async def _noop() -> None:
    pass


class TestScheduler:
    def test_get_ready_tasks_initial(self) -> None:
        dag = DAG()
        dag.add_edge("a", "b")
        tasks = {
            "a": Task(name="a", func=_noop),
            "b": Task(name="b", func=_noop, depends_on=["a"]),
        }
        sched = Scheduler()
        ready = sched.get_ready_tasks(dag, tasks)
        assert [t.name for t in ready] == ["a"]

    def test_get_ready_after_completion(self) -> None:
        dag = DAG()
        dag.add_edge("a", "b")
        tasks = {
            "a": Task(name="a", func=_noop, status=TaskStatus.SUCCESS),
            "b": Task(name="b", func=_noop, depends_on=["a"]),
        }
        sched = Scheduler()
        sched.mark_completed("a")
        ready = sched.get_ready_tasks(dag, tasks)
        assert [t.name for t in ready] == ["b"]

    def test_reset_clears_state(self) -> None:
        sched = Scheduler()
        sched.mark_completed("x")
        sched.mark_failed("y")
        sched.mark_running("z")
        sched.reset()
        assert sched.completed_count == 0
        assert not sched.has_failures
        assert sched.is_complete

    def test_properties(self) -> None:
        sched = Scheduler()
        assert sched.is_complete
        sched.mark_running("a")
        assert not sched.is_complete
        sched.mark_failed("a")
        assert sched.has_failures
