"""Tests for execution hooks (middleware)."""

from __future__ import annotations

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.hooks import TaskHook
from flowmesh.core.models import Task, TaskResult, TaskStatus, Workflow


class RecordingHook(TaskHook):
    """Hook that records calls for testing."""

    def __init__(self) -> None:
        self.before_calls: list[str] = []
        self.after_calls: list[tuple[str, str]] = []

    async def before_task(self, task: Task, workflow: Workflow) -> None:
        self.before_calls.append(task.name)

    async def after_task(self, task: Task, result: TaskResult, workflow: Workflow) -> None:
        self.after_calls.append((task.name, result.status.value))


class TestTaskHooks:
    """Verify that hooks are invoked around task execution."""

    async def test_hooks_called_on_success(self) -> None:
        """Before and after hooks fire for successful tasks."""

        async def noop() -> str:
            return "ok"

        hook = RecordingHook()
        wf = Workflow(
            name="hook-test",
            tasks=[Task(name="t1", func=noop), Task(name="t2", func=noop, depends_on=["t1"])],
        )

        engine = ExecutionEngine(hooks=[hook])
        await engine.execute(wf)

        assert hook.before_calls == ["t1", "t2"]
        assert hook.after_calls == [("t1", "success"), ("t2", "success")]

    async def test_hooks_called_on_failure(self) -> None:
        """After hook fires even when a task fails."""

        async def fail() -> None:
            raise RuntimeError("boom")

        hook = RecordingHook()
        wf = Workflow(name="fail-hook", tasks=[Task(name="t1", func=fail)])

        engine = ExecutionEngine(hooks=[hook])
        await engine.execute(wf)

        assert hook.before_calls == ["t1"]
        assert hook.after_calls == [("t1", "failed")]

    async def test_multiple_hooks(self) -> None:
        """Multiple hooks are all invoked in order."""

        async def noop() -> str:
            return "ok"

        hook1 = RecordingHook()
        hook2 = RecordingHook()
        wf = Workflow(name="multi-hook", tasks=[Task(name="t", func=noop)])

        engine = ExecutionEngine(hooks=[hook1, hook2])
        await engine.execute(wf)

        assert hook1.before_calls == ["t"]
        assert hook2.before_calls == ["t"]

    async def test_no_hooks_backward_compat(self) -> None:
        """Engine works fine without hooks (backward compatibility)."""

        async def noop() -> str:
            return "ok"

        wf = Workflow(name="no-hook", tasks=[Task(name="t", func=noop)])
        engine = ExecutionEngine()
        results = await engine.execute(wf)

        assert results["t"].status == TaskStatus.SUCCESS

    async def test_hooks_not_called_for_skipped_tasks(self) -> None:
        """Hooks are not invoked for tasks that are conditionally skipped."""

        async def produce() -> int:
            return 10

        async def consume() -> None:
            pass

        hook = RecordingHook()
        wf = Workflow(
            name="skip-hook",
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

        engine = ExecutionEngine(hooks=[hook])
        await engine.execute(wf)

        # Only "produce" should trigger hooks — "consume" is skipped
        assert hook.before_calls == ["produce"]
        assert len(hook.after_calls) == 1
        assert hook.after_calls[0][0] == "produce"
