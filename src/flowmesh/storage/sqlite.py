"""SQLite-backed implementation of :class:`WorkflowStore`.

Provides durable persistence that survives process restarts.  Uses
Python's built-in :mod:`sqlite3` module with ``asyncio`` wrappers so
no external database server is required.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from flowmesh.core.models import TaskResult, TaskStatus, Workflow, WorkflowStatus
from flowmesh.storage.base import WorkflowStore

_DEFAULT_DB_PATH = "flowmesh.db"


async def _noop() -> None:
    """Placeholder callable for deserialized tasks."""

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS workflows (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    task_defs   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS task_results (
    workflow_id TEXT NOT NULL,
    task_name   TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    status      TEXT NOT NULL,
    output      TEXT,
    error       TEXT,
    started_at  TEXT,
    finished_at TEXT,
    PRIMARY KEY (workflow_id, task_name),
    FOREIGN KEY (workflow_id) REFERENCES workflows(id) ON DELETE CASCADE
);
"""


class SQLiteWorkflowStore(WorkflowStore):
    """SQLite-backed workflow store for durable persistence."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # WorkflowStore interface
    # ------------------------------------------------------------------

    async def save(self, workflow: Workflow) -> None:
        task_defs = json.dumps(
            [
                {
                    "name": t.name,
                    "depends_on": t.depends_on,
                    "timeout_seconds": t.timeout_seconds,
                    "retry_count": t.retry_count,
                    "priority": t.priority,
                    "metadata": t.metadata,
                }
                for t in workflow.tasks
            ]
        )
        self._conn.execute(
            "INSERT OR REPLACE INTO workflows (id, name, status, created_at, metadata, task_defs) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                workflow.id,
                workflow.name,
                workflow.status.value,
                workflow.created_at.isoformat(),
                json.dumps(workflow.metadata),
                task_defs,
            ),
        )
        self._conn.commit()

    async def get(self, workflow_id: str) -> Workflow | None:
        row = self._conn.execute(
            "SELECT id, name, status, created_at, metadata, task_defs FROM workflows WHERE id = ?",
            (workflow_id,),
        ).fetchone()
        if not row:
            return None
        return self._row_to_workflow(row)

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Workflow]:
        rows = self._conn.execute(
            "SELECT id, name, status, created_at, metadata, task_defs "
            "FROM workflows ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [self._row_to_workflow(r) for r in rows]

    async def update_status(self, workflow_id: str, status: WorkflowStatus) -> None:
        self._conn.execute(
            "UPDATE workflows SET status = ? WHERE id = ?",
            (status.value, workflow_id),
        )
        self._conn.commit()

    async def save_results(self, workflow_id: str, results: dict[str, TaskResult]) -> None:
        for task_name, r in results.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO task_results "
                "(workflow_id, task_name, task_id, status, output, error, started_at, finished_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    workflow_id,
                    task_name,
                    r.task_id,
                    r.status.value,
                    json.dumps(r.output) if r.output is not None else None,
                    r.error,
                    r.started_at.isoformat() if r.started_at else None,
                    r.finished_at.isoformat() if r.finished_at else None,
                ),
            )
        self._conn.commit()

    async def get_results(self, workflow_id: str) -> dict[str, TaskResult] | None:
        rows = self._conn.execute(
            "SELECT task_name, task_id, status, output, error, started_at, finished_at "
            "FROM task_results WHERE workflow_id = ?",
            (workflow_id,),
        ).fetchall()
        if not rows:
            return None
        results: dict[str, TaskResult] = {}
        for row in rows:
            task_name, task_id, status, output, error, started_at, finished_at = row
            results[task_name] = TaskResult(
                task_id=task_id,
                status=TaskStatus(status),
                output=json.loads(output) if output is not None else None,
                error=error,
                started_at=datetime.fromisoformat(started_at) if started_at else None,
                finished_at=datetime.fromisoformat(finished_at) if finished_at else None,
            )
        return results

    async def delete(self, workflow_id: str) -> bool:
        """Delete a workflow and its results. Returns True if found."""
        cursor = self._conn.execute("DELETE FROM workflows WHERE id = ?", (workflow_id,))
        self._conn.commit()
        return cursor.rowcount > 0

    async def count_by_status(self) -> dict[str, int]:
        """Return workflow counts grouped by status."""
        rows = self._conn.execute(
            "SELECT status, COUNT(*) FROM workflows GROUP BY status"
        ).fetchall()
        return {row[0]: row[1] for row in rows}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_workflow(row: Any) -> Workflow:
        from flowmesh.core.models import Task

        wf_id, name, status, created_at, metadata_json, task_defs_json = row
        metadata = json.loads(metadata_json)
        task_defs = json.loads(task_defs_json)

        tasks = [
            Task(
                name=td["name"],
                func=_noop,
                depends_on=td.get("depends_on", []),
                timeout_seconds=td.get("timeout_seconds", 300.0),
                retry_count=td.get("retry_count", 0),
                priority=td.get("priority", 0),
                metadata=td.get("metadata", {}),
            )
            for td in task_defs
        ]

        return Workflow(
            name=name,
            tasks=tasks,
            id=wf_id,
            status=WorkflowStatus(status),
            created_at=datetime.fromisoformat(created_at),
            metadata=metadata,
        )
