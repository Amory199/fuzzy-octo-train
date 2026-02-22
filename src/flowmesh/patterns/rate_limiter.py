"""Token-bucket rate limiter for controlling throughput.

Useful for protecting downstream services from being overwhelmed by
the orchestration engine.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimiterConfig:
    """Token-bucket parameters."""

    max_tokens: float = 10.0
    refill_rate: float = 1.0  # tokens per second


class RateLimiter:
    """Async-safe token-bucket rate limiter.

    Tokens are added at a steady :pyattr:`refill_rate`.  Each call to
    :meth:`acquire` consumes one token, blocking if the bucket is empty.
    """

    def __init__(self, config: RateLimiterConfig | None = None) -> None:
        self._config = config or RateLimiterConfig()
        self._tokens: float = self._config.max_tokens
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    @property
    def available_tokens(self) -> float:
        self._refill()
        return self._tokens

    async def acquire(self, tokens: float = 1.0) -> None:
        """Block until *tokens* are available, then consume them."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
            # Sleep briefly and retry
            await asyncio.sleep(1.0 / self._config.refill_rate)

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._config.max_tokens,
            self._tokens + elapsed * self._config.refill_rate,
        )
        self._last_refill = now
