"""Circuit Breaker pattern for fault isolation.

Prevents cascading failures by tracking error rates and temporarily
halting calls to a failing dependency.  Implements the classic three-state
model: **Closed → Open → Half-Open**.
"""

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """Raised when a call is attempted while the circuit is open."""


@dataclass
class CircuitBreakerConfig:
    """Tuning parameters for the circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout_seconds: float = 30.0
    half_open_max_calls: int = 1


class CircuitBreaker:
    """Async-safe circuit breaker.

    Thread-/task-safe via :class:`asyncio.Lock`.  The breaker tracks
    consecutive failures and, once the threshold is reached, opens the
    circuit for a configurable cool-down period before allowing a
    tentative *half-open* probe.
    """

    def __init__(self, config: CircuitBreakerConfig | None = None) -> None:
        self._config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count: int = 0
        self._success_count: int = 0
        self._last_failure_time: float = 0
        self._half_open_calls: int = 0
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    async def call(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Invoke *func* through the circuit breaker.

        Raises :class:`CircuitOpenError` if the circuit is open and the
        recovery timeout has not yet elapsed.
        """
        async with self._lock:
            self._maybe_transition()

            if self._state == CircuitState.OPEN:
                raise CircuitOpenError(
                    f"Circuit is open — retry after {self._config.recovery_timeout_seconds}s"
                )

            if self._state == CircuitState.HALF_OPEN:
                if self._half_open_calls >= self._config.half_open_max_calls:
                    raise CircuitOpenError("Half-open call limit reached")
                self._half_open_calls += 1

        # Execute outside the lock so other calls aren't blocked.
        try:
            result = await func(*args, **kwargs)
        except Exception:
            await self._record_failure()
            raise

        await self._record_success()
        return result

    # ------------------------------------------------------------------

    def _maybe_transition(self) -> None:
        """Transition from OPEN → HALF_OPEN if the timeout has elapsed."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._config.recovery_timeout_seconds:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0

    async def _record_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._success_count = 0
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._config.failure_threshold:
                self._state = CircuitState.OPEN

    async def _record_success(self) -> None:
        async with self._lock:
            self._success_count += 1
            if self._state == CircuitState.HALF_OPEN:
                # Probe succeeded — close the circuit.
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._half_open_calls = 0
