"""Tests for API key authentication middleware."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from flowmesh.api.app import create_app


@pytest.fixture()
def app_with_auth(monkeypatch):
    """Create an app with API key authentication enabled."""
    monkeypatch.setenv("FLOWMESH_API_KEY", "test-secret-key")
    return create_app()


@pytest.fixture()
def app_without_auth(monkeypatch):
    """Create an app without API key authentication."""
    monkeypatch.delenv("FLOWMESH_API_KEY", raising=False)
    return create_app()


@pytest.fixture()
async def auth_client(app_with_auth):
    transport = ASGITransport(app=app_with_auth)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture()
async def noauth_client(app_without_auth):
    transport = ASGITransport(app=app_without_auth)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


class TestAPIKeyAuth:
    @pytest.mark.asyncio
    async def test_health_always_public(self, auth_client: AsyncClient) -> None:
        """Health endpoint should be accessible without API key."""
        resp = await auth_client.get("/health")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_protected_endpoint_rejects_missing_key(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/workflows")
        assert resp.status_code == 401
        assert "API key" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_protected_endpoint_rejects_wrong_key(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/workflows", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_protected_endpoint_accepts_valid_key(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/workflows", headers={"X-API-Key": "test-secret-key"})
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_api_key_via_query_param(self, auth_client: AsyncClient) -> None:
        resp = await auth_client.get("/workflows?api_key=test-secret-key")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_no_auth_when_disabled(self, noauth_client: AsyncClient) -> None:
        """All endpoints should be accessible when FLOWMESH_API_KEY is not set."""
        resp = await noauth_client.get("/workflows")
        assert resp.status_code == 200


class TestDeleteEndpoint:
    @pytest.mark.asyncio
    async def test_delete_workflow(self, noauth_client: AsyncClient) -> None:
        # Create a workflow
        payload = {
            "name": "to-delete",
            "tasks": [{"name": "step1"}],
        }
        create_resp = await noauth_client.post("/workflows", json=payload)
        assert create_resp.status_code == 201
        wf_id = create_resp.json()["id"]

        # Delete it
        del_resp = await noauth_client.delete(f"/workflows/{wf_id}")
        assert del_resp.status_code == 204

        # Verify it's gone
        get_resp = await noauth_client.get(f"/workflows/{wf_id}")
        assert get_resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_not_found(self, noauth_client: AsyncClient) -> None:
        resp = await noauth_client.delete("/workflows/nonexistent")
        assert resp.status_code == 404
