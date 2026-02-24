"""Authentication and authorization middleware for FlowMesh API.

Provides API key and JWT token-based authentication with RBAC support.

Usage:
    from flowmesh.auth import APIKeyAuth, JWTAuth, require_permission

    # API Key authentication
    api_auth = APIKeyAuth(api_keys={"key123": {"user": "admin", "roles": ["admin"]}})

    # JWT authentication
    jwt_auth = JWTAuth(secret_key="your-secret-key")

    # Apply to FastAPI
    app.add_middleware(APIKeyAuthMiddleware, auth=api_auth)

    # Protect endpoints
    @app.get("/admin")
    @require_permission("admin")
    async def admin_endpoint():
        return {"message": "Admin only"}
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class APIKeyAuth:
    """API key-based authentication.

    Validates requests using X-API-Key header.

    Args:
        api_keys: Dict mapping API keys to user info {"key": {"user": "name", "roles": [...]}}
    """

    def __init__(self, api_keys: dict[str, dict[str, Any]]) -> None:
        self._api_keys = api_keys

    def validate(self, api_key: str) -> dict[str, Any] | None:
        """Validate API key and return user info.

        Args:
            api_key: API key from request header

        Returns:
            User info dict if valid, None otherwise
        """
        return self._api_keys.get(api_key)


class JWTAuth:
    """JWT token-based authentication.

    Validates and generates JWT tokens for authenticated users.

    Args:
        secret_key: Secret key for signing tokens
        algorithm: JWT algorithm (default: HS256)
        expiration_minutes: Token expiration time (default: 60)
    """

    def __init__(
        self,
        secret_key: str,
        algorithm: str = "HS256",
        expiration_minutes: int = 60,
    ) -> None:
        self._secret_key = secret_key
        self._algorithm = algorithm
        self._expiration_minutes = expiration_minutes

        # Try to import jwt
        try:
            import jwt  # noqa: F401
        except ImportError:
            logger.warning(
                "PyJWT not installed. JWT auth will not work. Install with: pip install pyjwt"
            )

    def generate_token(self, user_id: str, roles: list[str]) -> str:
        """Generate a JWT token for a user.

        Args:
            user_id: User identifier
            roles: List of user roles

        Returns:
            Encoded JWT token

        Raises:
            ImportError: If PyJWT is not installed
        """
        import jwt

        payload = {
            "user_id": user_id,
            "roles": roles,
            "exp": datetime.now(UTC) + timedelta(minutes=self._expiration_minutes),
            "iat": datetime.now(UTC),
        }

        return jwt.encode(payload, self._secret_key, algorithm=self._algorithm)

    def validate(self, token: str) -> dict[str, Any] | None:
        """Validate JWT token and return payload.

        Args:
            token: JWT token from request

        Returns:
            Token payload if valid, None otherwise
        """
        try:
            import jwt

            payload = jwt.decode(token, self._secret_key, algorithms=[self._algorithm])
            return payload
        except ImportError:
            logger.error("PyJWT not installed")
            return None
        except Exception as exc:
            logger.debug(f"Token validation failed: {exc}")
            return None


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for API key authentication.

    Checks X-API-Key header on all requests except health checks.
    """

    def __init__(self, app: Any, auth: APIKeyAuth) -> None:
        super().__init__(app)
        self._auth = auth

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """Process request and validate API key."""
        # Skip auth for health check and docs
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json"]:
            return await call_next(request)

        # Get API key from header
        api_key = request.headers.get("X-API-Key")
        if not api_key:
            return HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing API key",
            )

        # Validate API key
        user_info = self._auth.validate(api_key)
        if not user_info:
            logger.warning(f"Invalid API key attempt from {request.client.host}")
            return HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API key",
            )

        # Attach user info to request state
        request.state.user = user_info

        return await call_next(request)


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Middleware for JWT token authentication.

    Checks Authorization header with Bearer token on all requests.
    """

    def __init__(self, app: Any, auth: JWTAuth) -> None:
        super().__init__(app)
        self._auth = auth

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """Process request and validate JWT token."""
        # Skip auth for health check, docs, and login endpoint
        if request.url.path in [
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/auth/login",
        ]:
            return await call_next(request)

        # Get token from header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid authorization header",
            )

        token = auth_header.split(" ")[1]

        # Validate token
        payload = self._auth.validate(token)
        if not payload:
            logger.warning(f"Invalid token attempt from {request.client.host}")
            return HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        # Attach user info to request state
        request.state.user = {
            "user_id": payload.get("user_id"),
            "roles": payload.get("roles", []),
        }

        return await call_next(request)


def require_role(required_role: str) -> Any:
    """Decorator to require a specific role for endpoint access.

    Args:
        required_role: Role name required to access the endpoint

    Example:
        @router.get("/admin")
        @require_role("admin")
        async def admin_endpoint(request: Request):
            return {"message": "Admin access granted"}
    """

    def decorator(func: Any) -> Any:
        async def wrapper(request: Request, *args: Any, **kwargs: Any) -> Any:
            user = getattr(request.state, "user", None)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Authentication required",
                )

            roles = user.get("roles", [])
            if required_role not in roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role '{required_role}' required",
                )

            return await func(request, *args, **kwargs)

        return wrapper

    return decorator


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple rate limiting middleware.

    Limits requests per IP address to prevent abuse.

    Args:
        app: FastAPI application
        requests_per_minute: Maximum requests allowed per minute per IP
    """

    def __init__(self, app: Any, requests_per_minute: int = 60) -> None:
        super().__init__(app)
        self._requests_per_minute = requests_per_minute
        self._requests: dict[str, list[float]] = {}

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        """Process request and enforce rate limit."""
        # Skip rate limiting for health checks
        if request.url.path in ["/health", "/metrics"]:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        current_time = time.time()

        # Clean old entries
        if client_ip in self._requests:
            self._requests[client_ip] = [
                t for t in self._requests[client_ip] if current_time - t < 60
            ]

        # Check rate limit
        if client_ip in self._requests:
            if len(self._requests[client_ip]) >= self._requests_per_minute:
                logger.warning(f"Rate limit exceeded for {client_ip}")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded",
                )

        # Record request
        if client_ip not in self._requests:
            self._requests[client_ip] = []
        self._requests[client_ip].append(current_time)

        return await call_next(request)
