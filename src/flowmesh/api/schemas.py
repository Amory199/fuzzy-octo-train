"""Pydantic schemas for request / response serialisation."""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — required at runtime by Pydantic

from pydantic import BaseModel, Field


class TaskDefinition(BaseModel):
    """Schema for defining a task inside a workflow submission."""

    name: str = Field(..., min_length=1, max_length=128)
    depends_on: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=300.0, gt=0)
    retry_count: int = Field(default=0, ge=0, le=10)
    metadata: dict[str, str] = Field(default_factory=dict)


class WorkflowCreate(BaseModel):
    """Schema for creating a new workflow."""

    name: str = Field(..., min_length=1, max_length=256)
    tasks: list[TaskDefinition] = Field(..., min_length=1)
    metadata: dict[str, str] = Field(default_factory=dict)


class TaskResultResponse(BaseModel):
    task_id: str
    status: str
    output: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: float | None = None


class WorkflowResponse(BaseModel):
    id: str
    name: str
    status: str
    created_at: datetime
    task_count: int
    metadata: dict[str, str] = Field(default_factory=dict)


class WorkflowDetailResponse(WorkflowResponse):
    results: dict[str, TaskResultResponse] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: str = "healthy"
    version: str
    uptime_seconds: float


class EngineStatsResponse(BaseModel):
    total_workflows: int
    pending: int
    running: int
    succeeded: int
    failed: int
