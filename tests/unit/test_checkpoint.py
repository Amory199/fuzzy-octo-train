"""Tests for workflow checkpointing and resume."""

from __future__ import annotations

import pytest

from flowmesh.core.checkpoint import InMemoryCheckpointStore
from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.models import Task, TaskStatus, Workflow


class TestCheckpointStore:
    """Verify InMemoryCheckpointStore operations."""

    async def test_save_and_load(self) -> None:
        from flowmesh.core.models import TaskResult

        store = InMemoryCheckpointStore()
        result = TaskResult(task_id="t1", status=TaskStatus.SUCCESS, output=42)

        await store.save_task_result("wf1", "task_a", result)
        cp = await store.load_checkpoint("wf1")

        assert cp is not None
        assert "task_a" in cp
        assert cp["task_a"].output == 42

    async def test_load_empty(self) -> None:
        store = InMemoryCheckpointStore()
        cp = await store.load_checkpoint("nonexistent")
        assert cp is None

    async def test_clear(self) -> None:
        from flowmesh.core.models import TaskResult

        store = InMemoryCheckpointStore()
        result = TaskResult(task_id="t1", status=TaskStatus.SUCCESS, output=1)
        await store.save_task_result("wf1", "a", result)
        await store.clear("wf1")
        assert await store.load_checkpoint("wf1") is None


class TestWorkflowResume:
    """Verify that a failed workflow can be resumed from its checkpoint."""

    async def test_resume_skips_completed_tasks(self) -> None:
        """Resumed execution does not re-run already-succeeded tasks."""
        call_counts: dict[str, int] = {"a": 0, "b": 0, "c": 0}

        async def task_a() -> int:
            call_counts["a"] += 1
            return 1

        async def task_b() -> int:
            call_counts["b"] += 1
            return 2

        fail_once = {"should_fail": True}

        async def task_c() -> int:
            call_counts["c"] += 1
            if fail_once["should_fail"]:
                fail_once["should_fail"] = False
                raise RuntimeError("transient error")
            return 3

        cp_store = InMemoryCheckpointStore()

        wf = Workflow(
            name="resume-test",
            tasks=[
                Task(name="a", func=task_a),
                Task(name="b", func=task_b, depends_on=["a"]),
                Task(name="c", func=task_c, depends_on=["b"]),
            ],
        )

        # First run — task_c fails
        engine = ExecutionEngine(checkpoint_store=cp_store)
        results = await engine.execute(wf)
        assert results["a"].status == TaskStatus.SUCCESS
        assert results["b"].status == TaskStatus.SUCCESS
        assert results["c"].status == TaskStatus.FAILED
        assert call_counts == {"a": 1, "b": 1, "c": 1}

        # Reset task states for re-execution
        for t in wf.tasks:
            if t.status == TaskStatus.FAILED:
                t.status = TaskStatus.PENDING
                t.result = None

        # Resume — should only re-run task_c
        results = await engine.resume(wf)
        assert results["c"].status == TaskStatus.SUCCESS
        assert results["c"].output == 3
        # task_a and task_b should NOT have been called again
        assert call_counts == {"a": 1, "b": 1, "c": 2}

    async def test_resume_without_store_raises(self) -> None:
        """Calling resume without a checkpoint store raises RuntimeError."""

        async def noop() -> None:
            pass

        wf = Workflow(name="no-store", tasks=[Task(name="t", func=noop)])
        engine = ExecutionEngine()

        with pytest.raises(RuntimeError, match="checkpoint store"):
            await engine.resume(wf)

    async def test_checkpoint_cleared_on_success(self) -> None:
        """After a fully successful resume the checkpoint is cleaned up."""

        async def noop() -> str:
            return "ok"

        cp_store = InMemoryCheckpointStore()

        wf = Workflow(name="clear-test", tasks=[Task(name="t", func=noop)])

        engine = ExecutionEngine(checkpoint_store=cp_store)
        await engine.execute(wf)

        # Checkpoint exists after execute
        cp = await cp_store.load_checkpoint(wf.id)
        assert cp is not None

        # Reset task for resume
        wf.tasks[0].status = TaskStatus.PENDING
        wf.tasks[0].result = None

        await engine.resume(wf)

        # Checkpoint cleared after successful resume
        cp = await cp_store.load_checkpoint(wf.id)
        assert cp is None

    async def test_checkpointing_during_execute(self) -> None:
        """Each completed task is checkpointed during normal execution."""

        async def task_a() -> int:
            return 1

        async def task_b() -> int:
            return 2

        cp_store = InMemoryCheckpointStore()
        wf = Workflow(
            name="cp-exec",
            tasks=[
                Task(name="a", func=task_a),
                Task(name="b", func=task_b, depends_on=["a"]),
            ],
        )

        engine = ExecutionEngine(checkpoint_store=cp_store)
        await engine.execute(wf)

        cp = await cp_store.load_checkpoint(wf.id)
        assert cp is not None
        assert "a" in cp
        assert "b" in cp
        assert cp["a"].output == 1
        assert cp["b"].output == 2
