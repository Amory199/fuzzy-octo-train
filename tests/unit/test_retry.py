"""Unit tests for retry with exponential backoff."""

from __future__ import annotations

import pytest

from flowmesh.patterns.retry import RetryPolicy, retry_with_backoff


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_succeeds_immediately(self) -> None:
        async def _ok() -> str:
            return "done"

        result = await retry_with_backoff(_ok, RetryPolicy(max_retries=3))
        assert result == "done"

    @pytest.mark.asyncio
    async def test_retries_then_succeeds(self) -> None:
        call_count = 0

        async def _flaky() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("transient")
            return "recovered"

        policy = RetryPolicy(max_retries=5, base_delay_seconds=0.001, jitter=False)
        result = await retry_with_backoff(_flaky, policy)
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_exhausts_retries(self) -> None:
        async def _always_fail() -> None:
            raise RuntimeError("permanent")

        policy = RetryPolicy(max_retries=2, base_delay_seconds=0.001, jitter=False)
        with pytest.raises(RuntimeError, match="permanent"):
            await retry_with_backoff(_always_fail, policy)

    @pytest.mark.asyncio
    async def test_zero_retries(self) -> None:
        async def _fail() -> None:
            raise RuntimeError("no retries")

        policy = RetryPolicy(max_retries=0)
        with pytest.raises(RuntimeError, match="no retries"):
            await retry_with_backoff(_fail, policy)
