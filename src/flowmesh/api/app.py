"""FastAPI application factory.

Creates and configures the ASGI application, wiring storage and
route dependencies.
"""

from __future__ import annotations

import uvicorn
from fastapi import FastAPI

from flowmesh import __version__
from flowmesh.api import routes
from flowmesh.storage.memory import InMemoryWorkflowStore


def create_app() -> FastAPI:
    """Build the configured FastAPI instance."""
    app = FastAPI(
        title="FlowMesh — Task Orchestration Engine",
        description=(
            "A distributed workflow engine with DAG-based scheduling, "
            "circuit-breaker fault isolation, and async-first execution."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    store = InMemoryWorkflowStore()
    routes.configure(store)
    app.include_router(routes.router)

    return app


def main() -> None:
    """Entry-point for ``flowmesh`` CLI."""
    uvicorn.run("flowmesh.api.app:create_app", factory=True, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
