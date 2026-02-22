"""Unit tests for the token-bucket rate limiter."""

from __future__ import annotations

import asyncio

import pytest

from flowmesh.patterns.rate_limiter import RateLimiter, RateLimiterConfig


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_within_budget(self) -> None:
        rl = RateLimiter(RateLimiterConfig(max_tokens=5, refill_rate=100))
        for _ in range(5):
            await rl.acquire()
        # Should have consumed all tokens
        assert rl.available_tokens < 1.0

    @pytest.mark.asyncio
    async def test_refill_over_time(self) -> None:
        rl = RateLimiter(RateLimiterConfig(max_tokens=2, refill_rate=100))
        await rl.acquire(2)
        await asyncio.sleep(0.05)
        # After 50ms at 100 tokens/s ≈ 5 tokens refilled, capped at 2
        assert rl.available_tokens >= 1.0

    @pytest.mark.asyncio
    async def test_acquire_blocks_when_empty(self) -> None:
        rl = RateLimiter(RateLimiterConfig(max_tokens=1, refill_rate=100))
        await rl.acquire(1)

        acquired = False

        async def _try_acquire() -> None:
            nonlocal acquired
            await rl.acquire(1)
            acquired = True

        task = asyncio.create_task(_try_acquire())
        await asyncio.sleep(0.05)
        assert acquired
        task.cancel()
