"""PostgreSQL-based workflow storage implementation.

Provides persistent, ACID-compliant storage for workflows using PostgreSQL.
Requires asyncpg for async database access.

Usage:
    store = PostgresWorkflowStore(
        dsn="postgresql://user:password@localhost:5432/flowmesh"
    )
    await store.initialize()  # Create tables
    await store.save(workflow)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from flowmesh.core.models import TaskResult, TaskStatus, Workflow, WorkflowStatus

if TYPE_CHECKING:
    from asyncpg import Pool

logger = logging.getLogger(__name__)


class PostgresWorkflowStore:
    """PostgreSQL-backed workflow storage with connection pooling.

    Creates two tables:
    - workflows: Stores workflow definitions and status
    - workflow_results: Stores task execution results

    Args:
        dsn: PostgreSQL connection string
        pool: Optional pre-configured connection pool
        min_pool_size: Minimum number of connections (default: 10)
        max_pool_size: Maximum number of connections (default: 20)
    """

    def __init__(
        self,
        dsn: str = "postgresql://localhost:5432/flowmesh",
        pool: Pool | None = None,
        min_pool_size: int = 10,
        max_pool_size: int = 20,
    ) -> None:
        self._dsn = dsn
        self._pool: Pool | None = pool
        self._min_pool_size = min_pool_size
        self._max_pool_size = max_pool_size
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize database connection pool and create tables."""
        if self._initialized:
            return

        if self._pool is None:
            try:
                import asyncpg
            except ImportError as exc:
                raise RuntimeError(
                    "asyncpg package not installed. Install with: pip install asyncpg"
                ) from exc

            self._pool = await asyncpg.create_pool(
                self._dsn,
                min_size=self._min_pool_size,
                max_size=self._max_pool_size,
            )

        # Create tables if they don't exist
        await self._create_tables()
        self._initialized = True

        logger.info("PostgreSQL workflow store initialized")

    async def _create_tables(self) -> None:
        """Create necessary database tables."""
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            # Workflows table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    metadata JSONB DEFAULT '{}',
                    tasks JSONB NOT NULL
                )
                """
            )

            # Create index on created_at for efficient listing
            await conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_workflows_created_at
                ON workflows(created_at DESC)
                """
            )

            # Workflow results table
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS workflow_results (
                    workflow_id TEXT PRIMARY KEY REFERENCES workflows(id) ON DELETE CASCADE,
                    results JSONB NOT NULL
                )
                """
            )

    async def save(self, workflow: Workflow) -> None:
        """Persist workflow definition."""
        if not self._initialized:
            await self.initialize()
        assert self._pool is not None

        # Serialize workflow tasks
        tasks_data = [
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

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflows (id, name, status, created_at, metadata, tasks)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    metadata = EXCLUDED.metadata,
                    tasks = EXCLUDED.tasks
                """,
                workflow.id,
                workflow.name,
                workflow.status.value,
                workflow.created_at,
                json.dumps(workflow.metadata),
                json.dumps(tasks_data),
            )

        logger.info(f"Saved workflow {workflow.id} to PostgreSQL")

    async def get(self, workflow_id: str) -> Workflow | None:
        """Retrieve workflow by ID."""
        if not self._initialized:
            await self.initialize()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, status, created_at, metadata, tasks
                FROM workflows
                WHERE id = $1
                """,
                workflow_id,
            )

        if not row:
            return None

        # Reconstruct workflow
        from flowmesh.core.models import Task

        async def _noop() -> None:
            pass

        tasks_data = json.loads(row["tasks"])
        tasks = [
            Task(
                name=t["name"],
                func=_noop,
                depends_on=t["depends_on"],
                timeout_seconds=t.get("timeout_seconds", 300.0),
                retry_count=t.get("retry_count", 0),
                priority=t.get("priority", 0),
                metadata=t.get("metadata", {}),
            )
            for t in tasks_data
        ]

        metadata = json.loads(row["metadata"]) if row["metadata"] else {}

        workflow = Workflow(name=row["name"], tasks=tasks, metadata=metadata)
        workflow.id = row["id"]
        workflow.status = WorkflowStatus(row["status"])

        return workflow

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Workflow]:
        """List workflows with pagination."""
        if not self._initialized:
            await self.initialize()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, name, status, created_at, metadata, tasks
                FROM workflows
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )

        workflows = []
        for row in rows:
            from flowmesh.core.models import Task

            async def _noop() -> None:
                pass

            tasks_data = json.loads(row["tasks"])
            tasks = [
                Task(
                    name=t["name"],
                    func=_noop,
                    depends_on=t["depends_on"],
                    timeout_seconds=t.get("timeout_seconds", 300.0),
                    retry_count=t.get("retry_count", 0),
                    priority=t.get("priority", 0),
                    metadata=t.get("metadata", {}),
                )
                for t in tasks_data
            ]

            metadata = json.loads(row["metadata"]) if row["metadata"] else {}

            workflow = Workflow(name=row["name"], tasks=tasks, metadata=metadata)
            workflow.id = row["id"]
            workflow.status = WorkflowStatus(row["status"])
            workflows.append(workflow)

        return workflows

    async def update_status(self, workflow_id: str, status: WorkflowStatus) -> None:
        """Update workflow status."""
        if not self._initialized:
            await self.initialize()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE workflows
                SET status = $1
                WHERE id = $2
                """,
                status.value,
                workflow_id,
            )

        logger.info(f"Updated workflow {workflow_id} status to {status.value}")

    async def save_results(self, workflow_id: str, results: dict[str, TaskResult]) -> None:
        """Persist task execution results."""
        if not self._initialized:
            await self.initialize()
        assert self._pool is not None

        # Serialize results
        results_data = {
            name: {
                "task_id": r.task_id,
                "status": r.status.value,
                "output": str(r.output) if r.output is not None else None,
                "error": r.error,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for name, r in results.items()
        }

        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO workflow_results (workflow_id, results)
                VALUES ($1, $2)
                ON CONFLICT (workflow_id) DO UPDATE SET
                    results = EXCLUDED.results
                """,
                workflow_id,
                json.dumps(results_data),
            )

        logger.info(f"Saved results for workflow {workflow_id} to PostgreSQL")

    async def get_results(self, workflow_id: str) -> dict[str, TaskResult] | None:
        """Retrieve task execution results."""
        if not self._initialized:
            await self.initialize()
        assert self._pool is not None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT results
                FROM workflow_results
                WHERE workflow_id = $1
                """,
                workflow_id,
            )

        if not row:
            return None

        results_dict = json.loads(row["results"])

        # Reconstruct TaskResult objects
        from datetime import datetime

        results = {}
        for name, r in results_dict.items():
            results[name] = TaskResult(
                task_id=r["task_id"],
                status=TaskStatus(r["status"]),
                output=r["output"],
                error=r["error"],
                started_at=(datetime.fromisoformat(r["started_at"]) if r["started_at"] else None),
                finished_at=(
                    datetime.fromisoformat(r["finished_at"]) if r["finished_at"] else None
                ),
            )

        return results

    async def close(self) -> None:
        """Close database connection pool."""
        if self._pool:
            await self._pool.close()
