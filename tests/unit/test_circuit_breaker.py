"""Unit tests for the circuit breaker pattern."""

from __future__ import annotations

import pytest

from flowmesh.patterns.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitOpenError,
    CircuitState,
)


async def _success() -> str:
    return "ok"


async def _failure() -> None:
    raise RuntimeError("service down")


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_by_default(self) -> None:
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_stays_closed_on_success(self) -> None:
        cb = CircuitBreaker()
        result = await cb.call(_success)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=3, recovery_timeout_seconds=60)
        cb = CircuitBreaker(config)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(_failure)
        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_rejects_when_open(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=1, recovery_timeout_seconds=60)
        cb = CircuitBreaker(config)
        with pytest.raises(RuntimeError):
            await cb.call(_failure)
        with pytest.raises(CircuitOpenError):
            await cb.call(_success)

    @pytest.mark.asyncio
    async def test_transitions_to_half_open(self) -> None:
        config = CircuitBreakerConfig(
            failure_threshold=1, recovery_timeout_seconds=0  # immediate recovery
        )
        cb = CircuitBreaker(config)
        with pytest.raises(RuntimeError):
            await cb.call(_failure)
        assert cb.state == CircuitState.OPEN
        # With recovery_timeout=0 the next call should probe half-open
        result = await cb.call(_success)
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_failure_count(self) -> None:
        config = CircuitBreakerConfig(failure_threshold=10)
        cb = CircuitBreaker(config)
        for _ in range(3):
            with pytest.raises(RuntimeError):
                await cb.call(_failure)
        assert cb.failure_count == 3
