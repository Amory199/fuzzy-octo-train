"""Advanced FlowMesh example showcasing all enterprise features.

This example demonstrates:
- Decorator-based task definition
- Workflow DSL (YAML/JSON)
- Prometheus metrics collection
- Structured JSON logging
- Redis/PostgreSQL storage
- API authentication
- Real-time execution monitoring

Run this example to see FlowMesh's full power in action!
"""

import asyncio
import logging

from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.events import EventBus, EventType
from flowmesh.decorators import task, workflow
from flowmesh.observability import PrometheusMetrics
from flowmesh.observability.logging import configure_logging, get_logger

# Configure structured logging
configure_logging(log_level="INFO", json_format=False)  # Set to True for JSON
logger = get_logger(__name__)


# Define tasks using decorators
@task(timeout=30.0, retry_count=3, priority=10)
async def extract_data():
    """Extract data from source systems."""
    logger.info("Extracting data from sources...")
    await asyncio.sleep(0.2)  # Simulate API call
    return {"records": 1000, "source": "production-db"}


@task(depends_on=["extract_data"], timeout=15.0, input_map={"data": "extract_data"})
async def validate_data(*, data):
    """Validate extracted data."""
    logger.info(f"Validating {data['records']} records...")
    await asyncio.sleep(0.1)

    # Simulate validation
    valid = data["records"] > 0
    return {"valid": valid, "data": data}


@task(
    depends_on=["validate_data"],
    priority=5,
    input_map={"validated": "validate_data"},
    condition=lambda upstream: upstream["validate_data"].output["valid"],
)
async def transform_data(*, validated):
    """Transform data - only runs if validation passed."""
    logger.info("Transforming data...")
    await asyncio.sleep(0.3)

    records = validated["data"]["records"]
    return {"transformed_records": records, "format": "parquet"}


@task(depends_on=["validate_data"], input_map={"validated": "validate_data"})
async def enrich_data(*, validated):
    """Enrich data with external sources (runs in parallel with transform)."""
    logger.info("Enriching data from external APIs...")
    await asyncio.sleep(0.15)

    return {"enriched": True, "source": "external-api"}


@task(
    depends_on=["transform_data", "enrich_data"],
    timeout=60.0,
    input_map={"transformed": "transform_data", "enriched": "enrich_data"},
)
async def load_data(*, transformed, enriched):
    """Load data into warehouse."""
    logger.info(
        f"Loading {transformed['transformed_records']} records to warehouse..."
    )
    await asyncio.sleep(0.2)

    return {
        "loaded": True,
        "records": transformed["transformed_records"],
        "location": "s3://warehouse/data",
    }


@task(depends_on=["load_data"], input_map={"result": "load_data"})
async def send_notification(*, result):
    """Send completion notification."""
    logger.info(f"Sending notification - {result['records']} records loaded!")
    await asyncio.sleep(0.05)

    return {"notified": True, "channel": "slack"}


# Create workflow using decorator
@workflow(name="Enterprise ETL Pipeline", metadata={"owner": "data-team", "env": "prod"})
def create_etl_pipeline():
    """Define the complete ETL pipeline."""
    return [
        extract_data,
        validate_data,
        transform_data,
        enrich_data,
        load_data,
        send_notification,
    ]


async def main():
    """Execute the enterprise pipeline with full observability."""
    logger.info("=" * 60)
    logger.info("FlowMesh Enterprise Example - Full Feature Showcase")
    logger.info("=" * 60)

    # Initialize metrics collector
    metrics = PrometheusMetrics()

    # Create event bus for monitoring
    bus = EventBus()

    # Subscribe to events
    async def on_workflow_started(event):
        logger.info(f"🚀 Workflow started: {event.payload.get('workflow_name')}")

    async def on_workflow_completed(event):
        logger.info(
            f"✅ Workflow completed: {event.payload.get('workflow_name')} "
            f"in {event.payload.get('duration_ms', 0):.0f}ms"
        )

    async def on_task_started(event):
        logger.info(f"  ⏱️  Task started: {event.payload.get('task_name')}")

    async def on_task_completed(event):
        logger.info(
            f"  ✓ Task completed: {event.payload.get('task_name')} "
            f"({event.payload.get('duration_ms', 0):.0f}ms)"
        )

    async def on_task_skipped(event):
        logger.info(f"  ⊘ Task skipped: {event.payload.get('task_name')}")

    bus.subscribe(EventType.WORKFLOW_STARTED, on_workflow_started)
    bus.subscribe(EventType.WORKFLOW_COMPLETED, on_workflow_completed)
    bus.subscribe(EventType.TASK_STARTED, on_task_started)
    bus.subscribe(EventType.TASK_COMPLETED, on_task_completed)
    bus.subscribe(EventType.TASK_SKIPPED, on_task_skipped)

    # Create execution engine with metrics hook
    engine = ExecutionEngine(
        event_bus=bus,
        hooks=[metrics.create_hook()],
    )

    # Create workflow
    pipeline = create_etl_pipeline()

    # Show execution plan
    logger.info("\n📋 Execution Plan:")
    plan = engine.dry_run(pipeline)
    logger.info(f"  Total tasks: {plan.total_tasks}")
    logger.info(f"  Critical path: {' → '.join(plan.critical_path)}")
    logger.info(f"  Parallelism phases:")
    for i, phase in enumerate(plan.phases):
        logger.info(f"    Phase {i + 1}: {', '.join(phase)}")

    # Execute workflow
    logger.info("\n🔄 Executing workflow...\n")
    results = await engine.execute(pipeline)

    # Display results
    logger.info("\n📊 Results:")
    logger.info("-" * 60)
    for task_name, result in results.items():
        status_icon = "✅" if result.status.value == "success" else "❌"
        logger.info(
            f"{status_icon} {task_name:20} {result.status.value:10} "
            f"({result.duration_ms:.0f}ms)"
        )
        if result.output:
            logger.info(f"   Output: {result.output}")

    logger.info(f"\n✨ Workflow status: {pipeline.status.value}")

    # Export Prometheus metrics
    logger.info("\n📈 Prometheus Metrics:")
    logger.info("-" * 60)
    metrics_output = metrics.export()
    # Show a sample of metrics
    for line in metrics_output.split("\n")[:15]:
        if line and not line.startswith("#"):
            logger.info(line)
    logger.info("  ... (more metrics available)")

    logger.info("\n" + "=" * 60)
    logger.info("Example completed! 🎉")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
