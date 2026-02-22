"""Integration tests for the FastAPI REST API."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from flowmesh.api.app import create_app


@pytest.fixture()
def app():
    return create_app()


@pytest.fixture()
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "uptime_seconds" in data


class TestWorkflowEndpoints:
    @pytest.mark.asyncio
    async def test_create_workflow(self, client: AsyncClient) -> None:
        payload = {
            "name": "ETL Pipeline",
            "tasks": [
                {"name": "extract"},
                {"name": "transform", "depends_on": ["extract"]},
                {"name": "load", "depends_on": ["transform"]},
            ],
        }
        resp = await client.post("/workflows", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "ETL Pipeline"
        assert data["task_count"] == 3
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_create_workflow_with_cycle(self, client: AsyncClient) -> None:
        payload = {
            "name": "bad",
            "tasks": [
                {"name": "a", "depends_on": ["b"]},
                {"name": "b", "depends_on": ["a"]},
            ],
        }
        resp = await client.post("/workflows", json=payload)
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_list_workflows(self, client: AsyncClient) -> None:
        await client.post(
            "/workflows",
            json={"name": "w1", "tasks": [{"name": "t1"}]},
        )
        resp = await client.get("/workflows")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

    @pytest.mark.asyncio
    async def test_get_workflow_detail(self, client: AsyncClient) -> None:
        create_resp = await client.post(
            "/workflows",
            json={"name": "detail-test", "tasks": [{"name": "t1"}]},
        )
        wf_id = create_resp.json()["id"]
        resp = await client.get(f"/workflows/{wf_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == wf_id

    @pytest.mark.asyncio
    async def test_get_workflow_not_found(self, client: AsyncClient) -> None:
        resp = await client.get("/workflows/nonexistent")
        assert resp.status_code == 404


class TestStatsEndpoint:
    @pytest.mark.asyncio
    async def test_stats(self, client: AsyncClient) -> None:
        resp = await client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_workflows" in data
