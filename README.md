<h1 align="center">🔀 FlowMesh</h1>
<p align="center">
  <strong>A distributed task orchestration engine with DAG-based scheduling, resilience patterns, and async-first execution.</strong>
</p>

<p align="center">
  <img alt="Python 3.11+" src="https://img.shields.io/badge/python-3.11%2B-blue?logo=python&logoColor=white" />
  <img alt="Test coverage" src="https://img.shields.io/badge/coverage-95%25-brightgreen" />
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green" />
  <img alt="CI" src="https://img.shields.io/github/actions/workflow/status/Amory199/fuzzy-octo-train/ci.yml?label=CI" />
</p>

---

## Overview

FlowMesh is a **production-grade workflow engine** built from the ground up in Python. It lets you define complex task pipelines as directed acyclic graphs (DAGs), executes them asynchronously with full dependency resolution, and protects downstream services using battle-tested resilience patterns.

### Key Features

| Feature | Description |
|---|---|
| **DAG-based scheduling** | Topological sort (Kahn's algorithm) ensures tasks run in valid dependency order |
| **Async execution engine** | `asyncio`-native with configurable concurrency via semaphore |
| **Task data flow** | Upstream task outputs automatically injected as kwargs to downstream tasks via `input_map` |
| **Conditional execution** | Tasks can declare conditions to dynamically skip based on upstream results |
| **Checkpointing & resume** | Persist state after each task; resume failed workflows without re-running completed steps |
| **Execution hooks** | `before_task` / `after_task` middleware for logging, metrics, and validation without modifying tasks |
| **Task priority** | Higher-priority tasks are dispatched first when multiple are ready simultaneously |
| **Dry run / execution plan** | Simulate workflow execution: see parallelism phases, critical path, and task ordering without running anything |
| **Circuit Breaker** | Three-state fault isolation (Closed → Open → Half-Open) prevents cascading failures |
| **Retry with backoff** | Exponential backoff with jitter for transient failure recovery |
| **Token-bucket rate limiter** | Protects downstream services from burst traffic |
| **Event-driven architecture** | Pub/sub event bus for decoupled lifecycle observation |
| **REST API** | FastAPI-powered HTTP interface with OpenAPI docs |
| **Pluggable storage** | Hexagonal architecture — swap in Redis, Postgres, etc. |
| **95% test coverage** | Unit + integration tests with pytest-asyncio |
| **Docker-ready** | Multi-stage Dockerfile with health checks |
| **CI/CD** | GitHub Actions pipeline with lint, test, type-check, and Docker build |

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     REST API (FastAPI)                    │
│              POST /workflows  GET /workflows             │
│              GET /health      GET /stats                 │
└─────────────────────────┬────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────┐
│                   Execution Engine                        │
│  ┌─────────┐  ┌───────────┐  ┌────────────────────────┐ │
│  │   DAG   │  │ Scheduler │  │     Event Bus          │ │
│  │ (topo-  │  │ (concurr- │  │ (pub/sub lifecycle     │ │
│  │  sort)  │  │  ency)    │  │  events)               │ │
│  └─────────┘  └───────────┘  └────────────────────────┘ │
│                                                          │
│  ┌──────────────── Resilience Layer ──────────────────┐  │
│  │  Circuit Breaker  │  Retry + Backoff  │ Rate Limit │  │
│  └───────────────────┴───────────────────┴────────────┘  │
└─────────────────────────┬────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────┐
│                   Storage Layer                           │
│     InMemoryStore  │  (Redis)  │  (PostgreSQL)           │
│        ✅ built-in │  🔌 plug  │  🔌 plug               │
└──────────────────────────────────────────────────────────┘
```

---

## Quick Start

### Installation

```bash
# Clone and install
git clone https://github.com/Amory199/fuzzy-octo-train.git
cd fuzzy-octo-train
pip install -e ".[dev]"
```

### Run the Example

```bash
python examples/basic_workflow.py
```

Output:
```
📥 Extracted 1,000 records
✅ Validated schema
🔄 Transformed records    ← runs in parallel with enrich
🧬 Enriched with external data
📤 Loaded into data warehouse
🔔 Sent completion notification

── Results ────────────────────────────────────
  extract:   success  (201ms)
  validate:  success  (100ms)
  transform: success  (301ms)
  enrich:    success  (151ms)
  load:      success  (200ms)
  notify:    success  (50ms)

Workflow status: success
```

### Start the API Server

```bash
# Development
uvicorn flowmesh.api.app:create_app --factory --reload

# Production (Docker)
docker compose up -d
```

Then open **http://localhost:8000/docs** for interactive API documentation.

---

## Usage

### Define a Workflow

```python
import asyncio
from flowmesh.core.engine import ExecutionEngine
from flowmesh.core.models import Task, Workflow

async def extract():
    # your extraction logic
    return {"records": 1000}

async def transform():
    return {"transformed": True}

async def load():
    return {"loaded": True}

workflow = Workflow(
    name="ETL Pipeline",
    tasks=[
        Task(name="extract", func=extract),
        Task(name="transform", func=transform, depends_on=["extract"]),
        Task(name="load", func=load, depends_on=["transform"]),
    ],
)

engine = ExecutionEngine()
results = asyncio.run(engine.execute(workflow))
```

### Add Resilience

```python
from flowmesh.patterns.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from flowmesh.patterns.retry import RetryPolicy

cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=5, recovery_timeout_seconds=30))
retry = RetryPolicy(max_retries=3, base_delay_seconds=0.1, jitter=True)

engine = ExecutionEngine(circuit_breaker=cb, default_retry=retry)
```

### Data Flow Between Tasks

Use `input_map` to pipe upstream outputs into downstream task arguments.
The DAG becomes a true **data pipeline** — not just dependency ordering.

```python
async def extract():
    return {"users": ["alice", "bob"], "count": 2}

async def transform(*, data):
    return [u.upper() for u in data["users"]]

async def load(*, records):
    return f"Loaded {len(records)} records"

workflow = Workflow(
    name="ETL with Data Flow",
    tasks=[
        Task(name="extract", func=extract),
        Task(name="transform", func=transform, depends_on=["extract"],
             input_map={"data": "extract"}),
        Task(name="load", func=load, depends_on=["transform"],
             input_map={"records": "transform"}),
    ],
)
```

### Conditional Execution

Skip expensive tasks dynamically based on upstream results:

```python
async def validate(*, data):
    return {"valid": len(data["users"]) > 0, "data": data}

async def expensive_enrichment(*, validated):
    # Only runs if validation passed
    return {"enriched": True}

workflow = Workflow(
    name="Conditional Pipeline",
    tasks=[
        Task(name="extract", func=extract),
        Task(name="validate", func=validate, depends_on=["extract"],
             input_map={"data": "extract"}),
        Task(name="enrich", func=expensive_enrichment, depends_on=["validate"],
             input_map={"validated": "validate"},
             condition=lambda upstream: upstream["validate"].output["valid"]),
    ],
)
```

### Checkpointing & Resume

Resume failed workflows without re-running completed steps — saves
massive compute cost on long pipelines:

```python
from flowmesh.core.checkpoint import InMemoryCheckpointStore

cp_store = InMemoryCheckpointStore()
engine = ExecutionEngine(checkpoint_store=cp_store)

# First run — if step 8 of 10 fails, steps 1-7 are checkpointed
results = engine.execute(workflow)

# Fix the issue, then resume from where it left off
results = engine.resume(workflow)
```

### Execution Hooks (Middleware)

Inject cross-cutting logic — logging, metrics, validation — without
modifying your task functions:

```python
from flowmesh.core.hooks import TaskHook

class MetricsHook(TaskHook):
    async def before_task(self, task, workflow):
        print(f"⏱ Starting {task.name}")

    async def after_task(self, task, result, workflow):
        print(f"✅ {task.name} → {result.status.value} ({result.duration_ms:.0f}ms)")

engine = ExecutionEngine(hooks=[MetricsHook()])
```

### Task Priority

When multiple tasks are ready, higher-priority tasks run first:

```python
workflow = Workflow(
    name="Prioritized Pipeline",
    tasks=[
        Task(name="critical", func=important_job, priority=10),
        Task(name="normal",   func=routine_job,   priority=0),
        Task(name="low",      func=background_job, priority=-5),
    ],
)
```

### Dry Run / Execution Plan

See exactly how a workflow *would* execute — parallelism phases,
critical path, and task count — without running anything:

```python
engine = ExecutionEngine()
plan = engine.dry_run(workflow)

print(plan.phases)               # [['extract'], ['transform', 'enrich'], ['load']]
print(plan.critical_path)        # ['extract', 'transform', 'load']
print(plan.critical_path_length) # 3
print(plan.total_tasks)          # 4
```

### Subscribe to Events

```python
from flowmesh.core.events import EventBus, EventType

bus = EventBus()

async def on_task_complete(event):
    print(f"Task {event.payload['task_name']} finished in {event.payload['duration_ms']:.0f}ms")

bus.subscribe(EventType.TASK_COMPLETED, on_task_complete)
engine = ExecutionEngine(event_bus=bus)
```

### REST API

```bash
# Create a workflow
curl -X POST http://localhost:8000/workflows \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Pipeline",
    "tasks": [
      {"name": "step1"},
      {"name": "step2", "depends_on": ["step1"]},
      {"name": "step3", "depends_on": ["step1"]},
      {"name": "step4", "depends_on": ["step2", "step3"]}
    ]
  }'

# List all workflows
curl http://localhost:8000/workflows

# Health check
curl http://localhost:8000/health
```

---

## Design Patterns Demonstrated

| Pattern | Location | Purpose |
|---|---|---|
| **DAG + Topological Sort** | `core/models.py` | Dependency resolution via Kahn's algorithm |
| **Data Flow Graph** | `core/engine.py` + `Task.input_map` | Upstream outputs auto-injected into downstream tasks |
| **Conditional Execution** | `core/engine.py` + `Task.condition` | Dynamic task skipping based on upstream results |
| **Checkpointing & Resume** | `core/checkpoint.py` | Persist completed tasks; resume failed workflows |
| **Middleware / Hooks** | `core/hooks.py` | Before/after task callbacks for cross-cutting concerns |
| **Priority Scheduling** | `core/scheduler.py` | Higher-priority tasks dispatched first |
| **Dry Run / Plan** | `core/engine.py` `dry_run()` | Execution plan with phases and critical path |
| **Circuit Breaker** | `patterns/circuit_breaker.py` | Fault isolation with three-state machine |
| **Retry with Exponential Backoff** | `patterns/retry.py` | Transient failure recovery |
| **Token Bucket Rate Limiter** | `patterns/rate_limiter.py` | Throughput protection |
| **Pub/Sub Event Bus** | `core/events.py` | Decoupled lifecycle notifications |
| **Hexagonal Architecture** | `storage/base.py` | Ports-and-adapters for pluggable persistence |
| **Repository Pattern** | `storage/memory.py` | Abstracted data access |
| **Factory Pattern** | `api/app.py` | Application assembly and DI |
| **Strategy Pattern** | Engine retry/CB | Interchangeable resilience strategies |
| **Command Pattern** | `core/models.Task` | Encapsulated async callables |

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest -v

# Run tests with coverage
pytest --cov=src/flowmesh --cov-report=term-missing

# Lint
ruff check src/ tests/

# Format
ruff format src/ tests/

# Type check
mypy src/flowmesh/
```

---

## Project Structure

```
├── src/flowmesh/
│   ├── core/
│   │   ├── models.py        # Task, Workflow, DAG (Kahn's toposort)
│   │   ├── engine.py        # Async execution engine + dry-run planner
│   │   ├── scheduler.py     # Priority-aware concurrency scheduler
│   │   ├── events.py        # Pub/sub event bus
│   │   ├── hooks.py         # Before/after task execution hooks
│   │   └── checkpoint.py    # Checkpoint store for resumable workflows
│   ├── patterns/
│   │   ├── circuit_breaker.py
│   │   ├── retry.py
│   │   └── rate_limiter.py
│   ├── api/
│   │   ├── app.py           # FastAPI factory
│   │   ├── routes.py        # REST endpoints
│   │   └── schemas.py       # Pydantic models
│   └── storage/
│       ├── base.py           # Abstract store (hexagonal port)
│       └── memory.py         # In-memory adapter
├── tests/
│   ├── unit/                 # 69 unit tests
│   └── integration/          # 7 API integration tests
├── examples/
│   ├── basic_workflow.py
│   └── data_pipeline.py
├── Dockerfile                # Multi-stage build
├── docker-compose.yml
├── pyproject.toml            # Modern Python packaging
└── .github/workflows/ci.yml  # CI pipeline
```

---

## License

MIT