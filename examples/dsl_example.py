"""Example of using FlowMesh Workflow DSL (YAML/JSON).

This example demonstrates:
- Loading workflow definitions from YAML files
- Registering task functions
- Validating workflow definitions
- Executing workflows defined declaratively

This approach is ideal for:
- Non-programmers defining workflows
- Version-controlled workflow definitions
- Dynamic workflow loading
- CI/CD pipelines
"""

import asyncio
import logging

from flowmesh.core.engine import ExecutionEngine
from flowmesh.dsl import WorkflowParser
from flowmesh.observability.logging import configure_logging, get_logger

# Configure logging
configure_logging(log_level="INFO", json_format=False)
logger = get_logger(__name__)


# Define task implementation functions
async def extract():
    """Extract data from source."""
    logger.info("📥 Extracting customer data...")
    await asyncio.sleep(0.2)
    return {"records": 5000, "source": "postgres://production"}


async def validate(*, data):
    """Validate data quality."""
    logger.info(f"✓ Validating {data['records']} records...")
    await asyncio.sleep(0.1)
    return {"valid": True, "data": data, "issues": 0}


async def transform(*, validated_data):
    """Transform and normalize data."""
    logger.info("🔄 Transforming data...")
    await asyncio.sleep(0.3)
    return {
        "transformed": True,
        "records": validated_data["data"]["records"],
        "format": "parquet",
    }


async def enrich(*, data):
    """Enrich with external data."""
    logger.info("🧬 Enriching with external sources...")
    await asyncio.sleep(0.15)
    return {"enriched": True, "sources": ["api.example.com"]}


async def load(*, transformed, enriched):
    """Load into data warehouse."""
    logger.info(f"📤 Loading {transformed['records']} records to warehouse...")
    await asyncio.sleep(0.2)
    return {"loaded": True, "location": "s3://warehouse/customers"}


async def notify(*, result):
    """Send completion notification."""
    logger.info(f"🔔 Pipeline complete! Data at {result['location']}")
    await asyncio.sleep(0.05)
    return {"notified": True}


async def main():
    """Load and execute workflow from YAML definition."""
    logger.info("=" * 70)
    logger.info("FlowMesh DSL Example - YAML Workflow Definition")
    logger.info("=" * 70)

    # Create parser
    parser = WorkflowParser()

    # Register task functions
    logger.info("\n📝 Registering task functions...")
    parser.register_task("extract", extract)
    parser.register_task("validate", validate)
    parser.register_task("transform", transform)
    parser.register_task("enrich", enrich)
    parser.register_task("load", load)
    parser.register_task("notify", notify)
    logger.info("   Registered 6 task functions")

    # Load workflow from YAML
    logger.info("\n📄 Loading workflow from pipeline.yaml...")
    try:
        workflow = parser.parse_file("examples/pipeline.yaml")
        logger.info(f"   ✓ Loaded workflow: {workflow.name}")
        logger.info(f"   ✓ Tasks: {len(workflow.tasks)}")
        logger.info(f"   ✓ Metadata: {workflow.metadata}")
    except Exception as exc:
        logger.error(f"   ✗ Failed to load workflow: {exc}")
        return

    # Create execution engine
    engine = ExecutionEngine()

    # Show execution plan
    logger.info("\n📋 Execution Plan:")
    plan = engine.dry_run(workflow)
    logger.info(f"   Total tasks: {plan.total_tasks}")
    logger.info(f"   Critical path: {' → '.join(plan.critical_path)}")
    logger.info(f"   Critical path length: {plan.critical_path_length}")
    logger.info(f"   Parallelism phases:")
    for i, phase in enumerate(plan.phases):
        logger.info(f"     Phase {i + 1}: {', '.join(phase)}")

    # Execute workflow
    logger.info("\n🔄 Executing workflow...\n")
    results = await engine.execute(workflow)

    # Display results
    logger.info("\n📊 Execution Results:")
    logger.info("-" * 70)
    for task_name, result in results.items():
        status_icon = "✅" if result.status.value == "success" else "❌"
        duration = f"{result.duration_ms:.0f}ms" if result.duration_ms else "N/A"
        logger.info(f"{status_icon} {task_name:15} {result.status.value:10} {duration:>8}")

    logger.info(f"\n✨ Workflow completed: {workflow.status.value}")
    logger.info("\n" + "=" * 70)

    # Show how to validate workflows
    logger.info("\n🔍 Workflow Validation Example:")
    logger.info("-" * 70)

    # Example of invalid workflow
    invalid_workflow = {
        "name": "Invalid Pipeline",
        "tasks": [
            {"name": "task1"},
            {
                "name": "task2",
                "depends_on": ["nonexistent"],
            },  # Invalid dependency
        ],
    }

    errors = parser.validate(invalid_workflow)
    if errors:
        logger.info("   Found validation errors:")
        for error in errors:
            logger.info(f"   ✗ {error}")
    else:
        logger.info("   ✓ Workflow is valid")

    logger.info("\n" + "=" * 70)
    logger.info("DSL Example completed! 🎉")
    logger.info("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
