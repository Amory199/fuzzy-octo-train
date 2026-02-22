"""Example: Data pipeline with resilience patterns.

Shows circuit breaker, retry, and rate limiting in action.
"""

import asyncio
import logging
import random

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.models import Task, Workflow
from flowmesh.patterns.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from flowmesh.patterns.retry import RetryPolicy

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)

# Simulated flaky counter
_call_count = 0


async def flaky_api_call() -> dict:
    """Simulate a service that fails intermittently."""
    global _call_count  # noqa: PLW0603
    _call_count += 1
    if random.random() < 0.5:  # noqa: S311
        raise ConnectionError(f"Timeout on attempt {_call_count}")
    return {"data": "payload", "attempt": _call_count}


async def process_data() -> dict:
    await asyncio.sleep(0.1)
    return {"processed": True}


async def store_results() -> dict:
    await asyncio.sleep(0.1)
    return {"stored": True}


async def main() -> None:
    cb = CircuitBreaker(
        CircuitBreakerConfig(failure_threshold=5, recovery_timeout_seconds=1.0)
    )
    retry_policy = RetryPolicy(max_retries=3, base_delay_seconds=0.01, jitter=True)

    workflow = Workflow(
        name="Resilient Pipeline",
        tasks=[
            Task(name="fetch", func=flaky_api_call, retry_count=3),
            Task(name="process", func=process_data, depends_on=["fetch"]),
            Task(name="store", func=store_results, depends_on=["process"]),
        ],
    )

    engine = ExecutionEngine(circuit_breaker=cb, default_retry=retry_policy)
    results = await engine.execute(workflow)

    print("\n── Resilient Pipeline Results ──────────────────")
    for name, result in results.items():
        status = result.status.value
        info = result.output or result.error
        print(f"  {name}: {status} — {info}")
    print(f"\nCircuit breaker state: {cb.state.value}")
    print(f"Failure count: {cb.failure_count}")


if __name__ == "__main__":
    asyncio.run(main())
