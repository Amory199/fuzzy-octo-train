"""FastAPI application factory.

Creates and configures the ASGI application, wiring storage and
route dependencies.  Integrates authentication, WebSocket event
broadcasting, and the web dashboard.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from flowmesh import __version__
from flowmesh.api import routes
from flowmesh.api.auth import APIKeyMiddleware

if TYPE_CHECKING:
    from flowmesh.api.websocket import ConnectionManager
    from flowmesh.core.events import Event


def _create_event_bridge(ws_manager: ConnectionManager) -> None:
    """Subscribe to all engine events and forward them via WebSocket."""

    async def _forward(event: Event) -> None:
        await ws_manager.broadcast(
            {
                "event_type": event.event_type.value,
                "payload": event.payload,
                "timestamp": event.timestamp.isoformat(),
            }
        )

    # This is called once at startup — the event bus itself is created
    # per-engine execution, so the bridge will be connected there.
    # We store the handler so the engine can register it.
    ws_manager._event_handler = _forward  # type: ignore[attr-defined]


def create_app() -> FastAPI:
    """Build the configured FastAPI instance."""
    app = FastAPI(
        title="FlowMesh — Task Orchestration Engine",
        description=(
            "A distributed workflow engine with DAG-based scheduling, "
            "circuit-breaker fault isolation, and async-first execution.  "
            "Includes a web dashboard, real-time WebSocket events, "
            "SQLite persistence, and API key authentication."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # --- Authentication middleware ---
    app.add_middleware(APIKeyMiddleware)

    # --- Storage backend ---
    storage_backend = os.environ.get("FLOWMESH_STORAGE", "memory")
    if storage_backend == "sqlite":
        from flowmesh.storage.sqlite import SQLiteWorkflowStore

        db_path = os.environ.get("FLOWMESH_DB_PATH", "flowmesh.db")
        store = SQLiteWorkflowStore(db_path=db_path)
    else:
        from flowmesh.storage.memory import InMemoryWorkflowStore

        store = InMemoryWorkflowStore()

    routes.configure(store)

    # --- WebSocket event bridge ---
    ws_manager = routes.get_ws_manager()
    _create_event_bridge(ws_manager)

    app.include_router(routes.router)

    # --- Dashboard static files ---
    import importlib.resources as pkg_resources

    dashboard_dir = pkg_resources.files("flowmesh") / "dashboard"
    if dashboard_dir.is_dir():  # type: ignore[union-attr]
        app.mount(
            "/dashboard",
            StaticFiles(directory=str(dashboard_dir), html=True),
            name="dashboard",
        )

    return app


def main() -> None:
    """Entry-point for ``flowmesh`` CLI."""
    uvicorn.run("flowmesh.api.app:create_app", factory=True, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
