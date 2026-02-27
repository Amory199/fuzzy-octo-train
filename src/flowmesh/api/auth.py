"""API key authentication middleware.

Provides a lightweight, configurable authentication layer.  When the
``FLOWMESH_API_KEY`` environment variable is set, every request
(except health checks and the dashboard) must include a matching
``X-API-Key`` header or ``api_key`` query parameter.

When the variable is **not** set, authentication is disabled so that
development and testing remain frictionless.
"""

from __future__ import annotations

import os
import secrets
from typing import TYPE_CHECKING

from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

if TYPE_CHECKING:
    from starlette.responses import Response

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


def _is_public(path: str) -> bool:
    """Return True if the path should skip authentication."""
    if path in _PUBLIC_PATHS:
        return True
    # Dashboard static assets
    return path.startswith("/dashboard")


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Reject requests that lack a valid API key.

    The expected key is read from the ``FLOWMESH_API_KEY`` environment
    variable at instantiation time.  If the variable is empty or unset,
    the middleware lets all requests through (auth disabled).
    """

    def __init__(self, app: object, api_key: str | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._api_key: str | None = api_key or os.environ.get("FLOWMESH_API_KEY") or None

    @property
    def enabled(self) -> bool:
        return self._api_key is not None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not self.enabled or _is_public(request.url.path):
            return await call_next(request)

        provided = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not provided or not secrets.compare_digest(provided, self._api_key):  # type: ignore[arg-type]
            from starlette.responses import JSONResponse

            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Invalid or missing API key"},
            )

        return await call_next(request)
