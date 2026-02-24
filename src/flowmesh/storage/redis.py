"""Redis-based workflow storage implementation.

Provides persistent, distributed storage for workflows using Redis.
Requires redis-py (asyncio support).

Usage:
    store = RedisWorkflowStore(redis_url="redis://localhost:6379/0")
    await store.save(workflow)
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from flowmesh.core.models import TaskResult, TaskStatus, Workflow, WorkflowStatus

if TYPE_CHECKING:
    from redis.asyncio import Redis


logger = logging.getLogger(__name__)


class RedisWorkflowStore:
    """Redis-backed workflow storage with connection pooling.

    Stores workflows as JSON in Redis with keys:
    - workflow:{workflow_id} - Full workflow definition
    - workflow:{workflow_id}:results - Task execution results
    - workflows:list - Sorted set of all workflow IDs (scored by creation time)

    Args:
        redis_url: Redis connection URL (e.g., redis://localhost:6379/0)
        redis_client: Optional pre-configured Redis client
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        redis_client: Redis[Any] | None = None,
    ) -> None:
        self._redis_url = redis_url
        self._redis: Redis[Any] | None = redis_client
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Lazy initialization of Redis connection."""
        if self._initialized:
            return

        if self._redis is None:
            try:
                from redis.asyncio import from_url

                self._redis = await from_url(self._redis_url, decode_responses=True)
            except ImportError as exc:
                raise RuntimeError(
                    "redis package not installed. Install with: pip install redis"
                ) from exc

        self._initialized = True

    async def save(self, workflow: Workflow) -> None:
        """Persist workflow definition."""
        await self._ensure_initialized()
        assert self._redis is not None

        # Serialize workflow (excluding task functions)
        workflow_data = {
            "id": workflow.id,
            "name": workflow.name,
            "status": workflow.status.value,
            "created_at": workflow.created_at.isoformat(),
            "metadata": workflow.metadata,
            "tasks": [
                {
                    "name": t.name,
                    "depends_on": t.depends_on,
                    "timeout_seconds": t.timeout_seconds,
                    "retry_count": t.retry_count,
                    "priority": t.priority,
                    "metadata": t.metadata,
                }
                for t in workflow.tasks
            ],
        }

        # Save to Redis
        key = f"workflow:{workflow.id}"
        await self._redis.set(key, json.dumps(workflow_data))

        # Add to sorted set (score = timestamp for ordering)
        await self._redis.zadd(
            "workflows:list",
            {workflow.id: workflow.created_at.timestamp()},
        )

        logger.info(f"Saved workflow {workflow.id} to Redis")

    async def get(self, workflow_id: str) -> Workflow | None:
        """Retrieve workflow by ID."""
        await self._ensure_initialized()
        assert self._redis is not None

        key = f"workflow:{workflow_id}"
        data = await self._redis.get(key)
        if not data:
            return None

        workflow_dict = json.loads(data)

        # Reconstruct workflow with noop functions
        from flowmesh.core.models import Task

        async def _noop() -> None:
            pass

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
            for t in workflow_dict["tasks"]
        ]

        workflow = Workflow(
            name=workflow_dict["name"],
            tasks=tasks,
            metadata=workflow_dict.get("metadata", {}),
        )
        workflow.id = workflow_dict["id"]
        workflow.status = WorkflowStatus(workflow_dict["status"])

        return workflow

    async def list_all(self, limit: int = 50, offset: int = 0) -> list[Workflow]:
        """List workflows with pagination."""
        await self._ensure_initialized()
        assert self._redis is not None

        # Get workflow IDs from sorted set (newest first)
        workflow_ids = await self._redis.zrevrange("workflows:list", offset, offset + limit - 1)

        workflows = []
        for wf_id in workflow_ids:
            wf = await self.get(str(wf_id))
            if wf:
                workflows.append(wf)

        return workflows

    async def update_status(self, workflow_id: str, status: WorkflowStatus) -> None:
        """Update workflow status."""
        await self._ensure_initialized()
        assert self._redis is not None

        wf = await self.get(workflow_id)
        if not wf:
            logger.warning(f"Workflow {workflow_id} not found for status update")
            return

        wf.status = status
        await self.save(wf)

    async def save_results(self, workflow_id: str, results: dict[str, TaskResult]) -> None:
        """Persist task execution results."""
        await self._ensure_initialized()
        assert self._redis is not None

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

        key = f"workflow:{workflow_id}:results"
        await self._redis.set(key, json.dumps(results_data))

        logger.info(f"Saved results for workflow {workflow_id} to Redis")

    async def get_results(self, workflow_id: str) -> dict[str, TaskResult] | None:
        """Retrieve task execution results."""
        await self._ensure_initialized()
        assert self._redis is not None

        key = f"workflow:{workflow_id}:results"
        data = await self._redis.get(key)
        if not data:
            return None

        results_dict = json.loads(data)

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
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()
