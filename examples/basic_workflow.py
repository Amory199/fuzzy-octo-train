"""Example: Basic ETL workflow using FlowMesh.

Demonstrates how to define tasks with dependencies, build a workflow,
and execute it through the engine with event logging.
"""

import asyncio
import logging

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.events import Event, EventBus, EventType
from flowmesh.core.models import Task, Workflow

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
log = logging.getLogger(__name__)


# ── Task implementations ─────────────────────────────────────────────


async def extract() -> dict:
    """Simulate data extraction from a source system."""
    await asyncio.sleep(0.2)
    log.info("📥 Extracted 1,000 records")
    return {"records": 1_000}


async def validate() -> dict:
    await asyncio.sleep(0.1)
    log.info("✅ Validated schema")
    return {"valid": True}


async def transform() -> dict:
    await asyncio.sleep(0.3)
    log.info("🔄 Transformed records")
    return {"transformed": 1_000}


async def enrich() -> dict:
    await asyncio.sleep(0.15)
    log.info("🧬 Enriched with external data")
    return {"enriched": 950}


async def load() -> dict:
    await asyncio.sleep(0.2)
    log.info("📤 Loaded into data warehouse")
    return {"loaded": 950}


async def notify() -> dict:
    await asyncio.sleep(0.05)
    log.info("🔔 Sent completion notification")
    return {"notified": True}


# ── Event listener ───────────────────────────────────────────────────


async def on_event(event: Event) -> None:
    log.info("⚡ Event: %s — %s", event.event_type.value, event.payload)


# ── Main ─────────────────────────────────────────────────────────────


async def main() -> None:
    bus = EventBus()
    for et in EventType:
        bus.subscribe(et, on_event)

    workflow = Workflow(
        name="ETL Pipeline",
        tasks=[
            Task(name="extract", func=extract),
            Task(name="validate", func=validate, depends_on=["extract"]),
            Task(name="transform", func=transform, depends_on=["validate"]),
            Task(name="enrich", func=enrich, depends_on=["validate"]),
            Task(name="load", func=load, depends_on=["transform", "enrich"]),
            Task(name="notify", func=notify, depends_on=["load"]),
        ],
        metadata={"owner": "data-team", "schedule": "daily"},
    )

    engine = ExecutionEngine(event_bus=bus)
    results = await engine.execute(workflow)

    print("\n── Results ────────────────────────────────────")
    for name, result in results.items():
        print(f"  {name}: {result.status.value}  ({result.duration_ms:.0f}ms)")
    print(f"\nWorkflow status: {workflow.status.value}")


if __name__ == "__main__":
    asyncio.run(main())
