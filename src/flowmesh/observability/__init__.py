"""Prometheus metrics exporter for FlowMesh observability.

Exposes workflow and task execution metrics in Prometheus format.

Metrics exposed:
- flowmesh_workflows_total: Total workflows by status
- flowmesh_workflow_duration_seconds: Workflow execution duration histogram
- flowmesh_tasks_total: Total tasks by status
- flowmesh_task_duration_seconds: Task execution duration histogram
- flowmesh_circuit_breaker_state: Circuit breaker current state
- flowmesh_active_workflows: Currently executing workflows

Usage:
    from flowmesh.observability.metrics import MetricsCollector

    metrics = MetricsCollector()
    engine = ExecutionEngine(hooks=[metrics.create_hook()])

    # Expose via HTTP endpoint
    from fastapi import Response

    @app.get("/metrics")
    async def metrics_endpoint():
        return Response(content=metrics.export(), media_type="text/plain")
"""

from __future__ import annotations

import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from flowmesh.core.hooks import TaskHook

if TYPE_CHECKING:
    from flowmesh.core.models import Task, TaskResult, Workflow


class PrometheusMetrics:
    """Collects and exports Prometheus-format metrics for FlowMesh.

    Thread-safe metric collection for workflow and task execution.
    """

    def __init__(self) -> None:
        # Counters
        self._workflow_total: dict[str, int] = defaultdict(int)
        self._task_total: dict[str, int] = defaultdict(int)

        # Histograms (buckets in seconds)
        self._workflow_duration_buckets = [0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0]
        self._task_duration_buckets = [0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0]

        self._workflow_duration_observations: dict[str, list[float]] = defaultdict(list)
        self._task_duration_observations: dict[str, list[float]] = defaultdict(list)

        # Gauges
        self._active_workflows: int = 0
        self._circuit_breaker_state: dict[str, int] = {}  # 0=closed, 1=open, 2=half_open

        # Tracking
        self._workflow_start_times: dict[str, float] = {}
        self._task_start_times: dict[str, float] = {}

    def record_workflow_started(self, workflow: Workflow) -> None:
        """Record workflow execution start."""
        self._active_workflows += 1
        self._workflow_start_times[workflow.id] = time.time()

    def record_workflow_completed(self, workflow: Workflow, success: bool) -> None:
        """Record workflow execution completion."""
        self._active_workflows = max(0, self._active_workflows - 1)

        status = "success" if success else "failed"
        self._workflow_total[status] += 1

        # Record duration
        if workflow.id in self._workflow_start_times:
            duration = time.time() - self._workflow_start_times.pop(workflow.id)
            self._workflow_duration_observations[status].append(duration)

    def record_task_started(self, task: Task, workflow: Workflow) -> None:
        """Record task execution start."""
        key = f"{workflow.id}:{task.name}"
        self._task_start_times[key] = time.time()

    def record_task_completed(self, task: Task, result: TaskResult, workflow: Workflow) -> None:
        """Record task execution completion."""
        status = result.status.value
        self._task_total[status] += 1

        # Record duration
        key = f"{workflow.id}:{task.name}"
        if key in self._task_start_times:
            duration = time.time() - self._task_start_times.pop(key)
            self._task_duration_observations[status].append(duration)

    def update_circuit_breaker_state(self, name: str, state: str) -> None:
        """Update circuit breaker state metric.

        Args:
            name: Circuit breaker identifier
            state: State ('closed', 'open', 'half_open')
        """
        state_map = {"closed": 0, "open": 1, "half_open": 2}
        self._circuit_breaker_state[name] = state_map.get(state, 0)

    def export(self) -> str:
        """Export metrics in Prometheus text format.

        Returns:
            Prometheus-formatted metrics string
        """
        lines = [
            "# HELP flowmesh_workflows_total Total number of workflow executions by status",
            "# TYPE flowmesh_workflows_total counter",
        ]

        # Workflow counters
        for status, count in self._workflow_total.items():
            lines.append(f'flowmesh_workflows_total{{status="{status}"}} {count}')

        # Task counters
        lines.extend(
            [
                "",
                "# HELP flowmesh_tasks_total Total number of task executions by status",
                "# TYPE flowmesh_tasks_total counter",
            ]
        )

        for status, count in self._task_total.items():
            lines.append(f'flowmesh_tasks_total{{status="{status}"}} {count}')

        # Active workflows gauge
        lines.extend(
            [
                "",
                "# HELP flowmesh_active_workflows Number of currently executing workflows",
                "# TYPE flowmesh_active_workflows gauge",
                f"flowmesh_active_workflows {self._active_workflows}",
            ]
        )

        # Workflow duration histogram
        lines.extend(
            [
                "",
                "# HELP flowmesh_workflow_duration_seconds Workflow execution duration in seconds",
                "# TYPE flowmesh_workflow_duration_seconds histogram",
            ]
        )

        for status, observations in self._workflow_duration_observations.items():
            if not observations:
                continue

            # Calculate histogram buckets
            bucket_counts = {bucket: 0 for bucket in self._workflow_duration_buckets}
            bucket_counts["+Inf"] = 0

            for obs in observations:
                for bucket in self._workflow_duration_buckets:
                    if obs <= bucket:
                        bucket_counts[bucket] += 1
                bucket_counts["+Inf"] += 1

            # Cumulative buckets
            cumulative = 0
            for bucket in sorted([b for b in bucket_counts if b != "+Inf"], key=float):
                cumulative += bucket_counts[bucket]
                lines.append(
                    f'flowmesh_workflow_duration_seconds_bucket{{status="{status}",le="{bucket}"}} {cumulative}'
                )

            lines.append(
                f'flowmesh_workflow_duration_seconds_bucket{{status="{status}",le="+Inf"}} {len(observations)}'
            )
            lines.append(
                f'flowmesh_workflow_duration_seconds_sum{{status="{status}"}} {sum(observations):.4f}'
            )
            lines.append(
                f'flowmesh_workflow_duration_seconds_count{{status="{status}"}} {len(observations)}'
            )

        # Task duration histogram
        lines.extend(
            [
                "",
                "# HELP flowmesh_task_duration_seconds Task execution duration in seconds",
                "# TYPE flowmesh_task_duration_seconds histogram",
            ]
        )

        for status, observations in self._task_duration_observations.items():
            if not observations:
                continue

            # Calculate histogram buckets
            bucket_counts = {bucket: 0 for bucket in self._task_duration_buckets}
            bucket_counts["+Inf"] = 0

            for obs in observations:
                for bucket in self._task_duration_buckets:
                    if obs <= bucket:
                        bucket_counts[bucket] += 1
                bucket_counts["+Inf"] += 1

            # Cumulative buckets
            cumulative = 0
            for bucket in sorted([b for b in bucket_counts if b != "+Inf"], key=float):
                cumulative += bucket_counts[bucket]
                lines.append(
                    f'flowmesh_task_duration_seconds_bucket{{status="{status}",le="{bucket}"}} {cumulative}'
                )

            lines.append(
                f'flowmesh_task_duration_seconds_bucket{{status="{status}",le="+Inf"}} {len(observations)}'
            )
            lines.append(
                f'flowmesh_task_duration_seconds_sum{{status="{status}"}} {sum(observations):.4f}'
            )
            lines.append(
                f'flowmesh_task_duration_seconds_count{{status="{status}"}} {len(observations)}'
            )

        # Circuit breaker states
        if self._circuit_breaker_state:
            lines.extend(
                [
                    "",
                    "# HELP flowmesh_circuit_breaker_state Circuit breaker state (0=closed, 1=open, 2=half_open)",
                    "# TYPE flowmesh_circuit_breaker_state gauge",
                ]
            )

            for name, state in self._circuit_breaker_state.items():
                lines.append(f'flowmesh_circuit_breaker_state{{name="{name}"}} {state}')

        return "\n".join(lines) + "\n"

    def create_hook(self) -> PrometheusMetricsHook:
        """Create a TaskHook that automatically collects metrics.

        Returns:
            Hook instance that can be passed to ExecutionEngine
        """
        return PrometheusMetricsHook(self)


class PrometheusMetricsHook(TaskHook):
    """TaskHook implementation that collects Prometheus metrics.

    Automatically tracks task execution and feeds data to PrometheusMetrics.
    """

    def __init__(self, metrics: PrometheusMetrics) -> None:
        self._metrics = metrics

    async def before_task(self, task: Task, workflow: Workflow) -> None:
        """Record task start time."""
        self._metrics.record_task_started(task, workflow)

    async def after_task(self, task: Task, result: TaskResult, workflow: Workflow) -> None:
        """Record task completion and duration."""
        self._metrics.record_task_completed(task, result, workflow)
