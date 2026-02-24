"""Tests for the SQLite workflow store."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from flowmesh.core.models import Task, TaskResult, TaskStatus, Workflow, WorkflowStatus
from flowmesh.storage.sqlite import SQLiteWorkflowStore


@pytest.fixture()
def store(tmp_path):
    """Create a SQLiteWorkflowStore backed by a temporary database."""
    db_path = str(tmp_path / "test.db")
    s = SQLiteWorkflowStore(db_path=db_path)
    yield s
    s.close()


async def _noop() -> None:
    pass


def _make_workflow(name: str = "test-wf") -> Workflow:
    return Workflow(
        name=name,
        tasks=[
            Task(name="extract", func=_noop),
            Task(name="transform", func=_noop, depends_on=["extract"]),
            Task(name="load", func=_noop, depends_on=["transform"]),
        ],
    )


class TestSQLiteWorkflowStore:
    @pytest.mark.asyncio
    async def test_save_and_get(self, store: SQLiteWorkflowStore) -> None:
        wf = _make_workflow()
        await store.save(wf)
        loaded = await store.get(wf.id)
        assert loaded is not None
        assert loaded.id == wf.id
        assert loaded.name == wf.name
        assert loaded.status == WorkflowStatus.PENDING
        assert len(loaded.tasks) == 3

    @pytest.mark.asyncio
    async def test_get_nonexistent(self, store: SQLiteWorkflowStore) -> None:
        result = await store.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_all(self, store: SQLiteWorkflowStore) -> None:
        for i in range(5):
            await store.save(_make_workflow(f"wf-{i}"))
        all_wf = await store.list_all()
        assert len(all_wf) == 5

    @pytest.mark.asyncio
    async def test_list_all_with_limit_and_offset(self, store: SQLiteWorkflowStore) -> None:
        for i in range(10):
            await store.save(_make_workflow(f"wf-{i}"))
        page = await store.list_all(limit=3, offset=2)
        assert len(page) == 3

    @pytest.mark.asyncio
    async def test_update_status(self, store: SQLiteWorkflowStore) -> None:
        wf = _make_workflow()
        await store.save(wf)
        await store.update_status(wf.id, WorkflowStatus.RUNNING)
        loaded = await store.get(wf.id)
        assert loaded is not None
        assert loaded.status == WorkflowStatus.RUNNING

    @pytest.mark.asyncio
    async def test_save_and_get_results(self, store: SQLiteWorkflowStore) -> None:
        wf = _make_workflow()
        await store.save(wf)

        now = datetime.now(UTC)
        results = {
            "extract": TaskResult(
                task_id="abc",
                status=TaskStatus.SUCCESS,
                output={"records": 100},
                started_at=now,
                finished_at=now,
            ),
            "transform": TaskResult(
                task_id="def",
                status=TaskStatus.FAILED,
                error="timeout",
                started_at=now,
                finished_at=now,
            ),
        }
        await store.save_results(wf.id, results)

        loaded = await store.get_results(wf.id)
        assert loaded is not None
        assert len(loaded) == 2
        assert loaded["extract"].status == TaskStatus.SUCCESS
        assert loaded["extract"].output == {"records": 100}
        assert loaded["transform"].error == "timeout"

    @pytest.mark.asyncio
    async def test_get_results_empty(self, store: SQLiteWorkflowStore) -> None:
        result = await store.get_results("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete(self, store: SQLiteWorkflowStore) -> None:
        wf = _make_workflow()
        await store.save(wf)
        assert await store.get(wf.id) is not None

        deleted = await store.delete(wf.id)
        assert deleted is True
        assert await store.get(wf.id) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store: SQLiteWorkflowStore) -> None:
        deleted = await store.delete("nonexistent")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_count_by_status(self, store: SQLiteWorkflowStore) -> None:
        for i in range(3):
            await store.save(_make_workflow(f"wf-{i}"))
        # Update one to running
        wfs = await store.list_all()
        await store.update_status(wfs[0].id, WorkflowStatus.RUNNING)

        counts = await store.count_by_status()
        assert counts.get("pending", 0) == 2
        assert counts.get("running", 0) == 1

    @pytest.mark.asyncio
    async def test_persistence_across_instances(self, tmp_path) -> None:
        """Data persists when a new store instance is created."""
        db_path = str(tmp_path / "persist.db")
        store1 = SQLiteWorkflowStore(db_path=db_path)
        wf = _make_workflow()
        await store1.save(wf)
        store1.close()

        store2 = SQLiteWorkflowStore(db_path=db_path)
        loaded = await store2.get(wf.id)
        assert loaded is not None
        assert loaded.name == wf.name
        store2.close()
