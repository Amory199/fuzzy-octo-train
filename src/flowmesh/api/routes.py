"""API route definitions — separated from the app factory for testability."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, status
from starlette.websockets import WebSocket, WebSocketDisconnect

from flowmesh import __version__
from flowmesh.api.schemas import (
    EngineStatsResponse,
    HealthResponse,
    TaskResultResponse,
    WorkflowCreate,
    WorkflowDetailResponse,
    WorkflowResponse,
)
from flowmesh.api.websocket import ConnectionManager
from flowmesh.core.models import WorkflowStatus

if TYPE_CHECKING:
    from flowmesh.storage.base import WorkflowStore

router = APIRouter()

# These are injected by the app factory via ``router.state``
_store: WorkflowStore | None = None
_start_time: float = time.monotonic()
_ws_manager: ConnectionManager = ConnectionManager()


def configure(store: WorkflowStore) -> None:
    """Wire the storage dependency into the router (poor-man's DI)."""
    global _store
    _store = store


def get_ws_manager() -> ConnectionManager:
    """Expose the WebSocket manager so the app factory can wire events."""
    return _ws_manager


def _get_store() -> WorkflowStore:
    if _store is None:
        raise RuntimeError("Store not configured")
    return _store


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


@router.delete(
    "/workflows/{workflow_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["workflows"],
)
async def delete_workflow(workflow_id: str) -> None:
    """Delete a workflow by ID."""
    store = _get_store()
    wf = await store.get(workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="Workflow not found")
    await store.delete(workflow_id)


# ------------------------------------------------------------------
# WebSocket — real-time events
# ------------------------------------------------------------------


@router.websocket("/ws/events")
async def websocket_events(ws: WebSocket) -> None:
    """Stream engine lifecycle events to connected clients."""
    await _ws_manager.connect(ws)
    try:
        while True:
            # Keep the connection alive; client sends pings
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_manager.disconnect(ws)
