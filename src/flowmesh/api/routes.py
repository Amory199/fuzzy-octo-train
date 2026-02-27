"""API route definitions — separated from the app factory for testability."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status
from starlette.websockets import WebSocket, WebSocketDisconnect

from flowmesh import __version__
from flowmesh.api.schemas import (
    EngineStatsResponse,
    HealthResponse,
    TaskResultResponse,
    WorkflowCancelResponse,
    WorkflowCreate,
    WorkflowDetailResponse,
    WorkflowExecutionResponse,
    WorkflowResponse,
)
from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.models import WorkflowStatus

if TYPE_CHECKING:
    from flowmesh.storage.base import WorkflowStore

logger = logging.getLogger(__name__)

router = APIRouter()

# These are injected by the app factory via ``router.state``
_store: WorkflowStore | None = None
_engine: ExecutionEngine | None = None
_start_time: float = time.monotonic()
_running_workflows: dict[str, asyncio.Task[None]] = {}


def configure(store: WorkflowStore, engine: ExecutionEngine | None = None) -> None:
    """Wire the storage dependency and execution engine into the router (poor-man's DI)."""
    global _store, _engine
    _store = store
    _engine = engine or ExecutionEngine()


def get_ws_manager() -> ConnectionManager:
    """Expose the WebSocket manager so the app factory can wire events."""
    return _ws_manager


def _get_store() -> WorkflowStore:
    if _store is None:
        raise RuntimeError("Store not configured")
    return _store


def _get_engine() -> ExecutionEngine:
    if _engine is None:
        raise RuntimeError("Engine not configured")
    return _engine


# ------------------------------------------------------------------
# Health & stats
# ------------------------------------------------------------------


@router.get("/health", response_model=HealthResponse, tags=["ops"])
async def health() -> HealthResponse:
    return HealthResponse(
        version=__version__,
        uptime_seconds=round(time.monotonic() - _start_time, 2),
    )


@router.get("/stats", response_model=EngineStatsResponse, tags=["ops"])
async def stats() -> EngineStatsResponse:
    store = _get_store()
    workflows = await store.list_all(limit=10_000)
    return EngineStatsResponse(
        total_workflows=len(workflows),
        pending=sum(1 for w in workflows if w.status == WorkflowStatus.PENDING),
        running=sum(1 for w in workflows if w.status == WorkflowStatus.RUNNING),
        succeeded=sum(1 for w in workflows if w.status == WorkflowStatus.SUCCESS),
        failed=sum(1 for w in workflows if w.status == WorkflowStatus.FAILED),
    )


# ------------------------------------------------------------------
# Workflow CRUD
# ------------------------------------------------------------------


@router.post(
    "/workflows",
    response_model=WorkflowResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["workflows"],
)
async def create_workflow(body: WorkflowCreate) -> WorkflowResponse:
    """Validate and persist a new workflow definition."""
    from flowmesh.core.models import Task, Workflow

    async def _noop() -> None:
        pass

    tasks = [
        Task(
            name=t.name,
            func=_noop,
            depends_on=t.depends_on,
            timeout_seconds=t.timeout_seconds,
            retry_count=t.retry_count,
            metadata=t.metadata,
        )
        for t in body.tasks
    ]
    wf = Workflow(name=body.name, tasks=tasks, metadata=body.metadata)

    try:
        wf.build_dag()  # validate
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc

    store = _get_store()
    await store.save(wf)

    return WorkflowResponse(
        id=wf.id,
        name=wf.name,
        status=wf.status.value,
        created_at=wf.created_at,
        task_count=len(wf.tasks),
        metadata=wf.metadata,
    )


@router.get("/workflows", response_model=list[WorkflowResponse], tags=["workflows"])
async def list_workflows(limit: int = 50, offset: int = 0) -> list[WorkflowResponse]:
    store = _get_store()
    workflows = await store.list_all(limit=limit, offset=offset)
    return [
        WorkflowResponse(
            id=w.id,
            name=w.name,
            status=w.status.value,
            created_at=w.created_at,
            task_count=len(w.tasks),
            metadata=w.metadata,
        )
        for w in workflows
    ]


@router.get(
    "/workflows/{workflow_id}",
    response_model=WorkflowDetailResponse,
    tags=["workflows"],
)
async def get_workflow(workflow_id: str) -> WorkflowDetailResponse:
    store = _get_store()
    wf = await store.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    raw_results = await store.get_results(workflow_id) or {}
    result_responses = {
        name: TaskResultResponse(
            task_id=r.task_id,
            status=r.status.value,
            output=str(r.output) if r.output is not None else None,
            error=r.error,
            started_at=r.started_at,
            finished_at=r.finished_at,
            duration_ms=r.duration_ms,
        )
        for name, r in raw_results.items()
    }

    return WorkflowDetailResponse(
        id=wf.id,
        name=wf.name,
        status=wf.status.value,
        created_at=wf.created_at,
        task_count=len(wf.tasks),
        metadata=wf.metadata,
        results=result_responses,
    )


# ------------------------------------------------------------------
# Workflow execution & control
# ------------------------------------------------------------------


async def _execute_workflow_background(workflow_id: str) -> None:
    """Execute a workflow in the background and persist results."""
    try:
        store = _get_store()
        engine = _get_engine()

        # Get workflow
        wf = await store.get(workflow_id)
        if not wf:
            logger.error(f"Workflow {workflow_id} not found for execution")
            return

        # Update status to running
        await store.update_status(workflow_id, WorkflowStatus.RUNNING)

        # Execute workflow
        logger.info(f"Starting execution of workflow {workflow_id}")
        results = await engine.execute(wf)

        # Save results
        await store.save_results(workflow_id, results)

        # Update final status
        final_status = (
            WorkflowStatus.SUCCESS
            if all(r.status == "success" for r in results.values())
            else WorkflowStatus.FAILED
        )
        await store.update_status(workflow_id, final_status)

        logger.info(f"Workflow {workflow_id} completed with status {final_status.value}")

    except Exception as exc:
        logger.exception(f"Error executing workflow {workflow_id}: {exc}")
        try:
            store = _get_store()
            await store.update_status(workflow_id, WorkflowStatus.FAILED)
        except Exception as save_exc:
            logger.exception(f"Failed to update workflow status after error: {save_exc}")
    finally:
        # Clean up tracking
        _running_workflows.pop(workflow_id, None)


@router.post(
    "/workflows/{workflow_id}/execute",
    response_model=WorkflowExecutionResponse,
    tags=["workflows"],
)
async def execute_workflow(
    workflow_id: str, background_tasks: BackgroundTasks
) -> WorkflowExecutionResponse:
    """Trigger async execution of a workflow.

    The workflow executes in the background. Poll GET /workflows/{workflow_id}
    to check status and retrieve results.
    """
    store = _get_store()
    wf = await store.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # Check if already running
    if workflow_id in _running_workflows:
        return WorkflowExecutionResponse(
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING.value,
            message="Workflow is already executing",
        )

    # Create background task
    task = asyncio.create_task(_execute_workflow_background(workflow_id))
    _running_workflows[workflow_id] = task

    return WorkflowExecutionResponse(
        workflow_id=workflow_id,
        status=WorkflowStatus.RUNNING.value,
        message="Workflow execution started",
    )


@router.delete(
    "/workflows/{workflow_id}",
    response_model=WorkflowCancelResponse,
    tags=["workflows"],
)
async def cancel_workflow(workflow_id: str) -> WorkflowCancelResponse:
    """Cancel a running workflow.

    Note: This cancels the workflow task but individual task execution
    may complete if already started.
    """
    if workflow_id not in _running_workflows:
        raise HTTPException(status_code=404, detail="Workflow not running or not found")

    # Cancel the task
    task = _running_workflows[workflow_id]
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass  # Expected when cancelling

    # Update status
    store = _get_store()
    await store.update_status(workflow_id, WorkflowStatus.CANCELLED)

    _running_workflows.pop(workflow_id, None)

    return WorkflowCancelResponse(
        workflow_id=workflow_id,
        status=WorkflowStatus.CANCELLED.value,
        message="Workflow cancelled successfully",
    )
