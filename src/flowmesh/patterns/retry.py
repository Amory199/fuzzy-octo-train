"""Retry with exponential backoff and optional jitter.

Provides a composable :func:`retry_with_backoff` helper that wraps any
async callable, re-invoking it on transient failures up to a
configurable limit.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    """Immutable configuration for retry behaviour."""

    max_retries: int = 3
    base_delay_seconds: float = 0.1
    max_delay_seconds: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True


async def retry_with_backoff(
    func: Callable[..., Coroutine[Any, Any, Any]],
    policy: RetryPolicy | None = None,
    *args: Any,
    **kwargs: Any,
) -> Any:
    """Execute *func* with exponential-backoff retries.

    On each failure the delay doubles (with optional jitter) up to
    *max_delay_seconds*.  After *max_retries* consecutive failures
    the last exception is re-raised.
    """
    policy = policy or RetryPolicy()
    last_exc: BaseException | None = None

    for attempt in range(policy.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            last_exc = exc
            if attempt == policy.max_retries:
                break
            delay = min(
                policy.base_delay_seconds * (policy.exponential_base ** attempt),
                policy.max_delay_seconds,
            )
            if policy.jitter:
                delay *= random.uniform(0.5, 1.5)
            logger.warning(
                "Attempt %d/%d failed (%s) — retrying in %.2fs",
                attempt + 1,
                policy.max_retries + 1,
                exc,
                delay,
            )
            await asyncio.sleep(delay)

    raise last_exc  # type: ignore[misc]
