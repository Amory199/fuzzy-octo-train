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
│   │   ├── engine.py        # Async execution engine
│   │   ├── scheduler.py     # Concurrency-controlled scheduler
│   │   └── events.py        # Pub/sub event bus
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
│   ├── unit/                 # 38 unit tests
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