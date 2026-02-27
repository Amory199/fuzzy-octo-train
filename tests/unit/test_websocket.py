"""Tests for the WebSocket connection manager."""

from __future__ import annotations

import pytest

from flowmesh.api.websocket import ConnectionManager


class TestConnectionManager:
    def test_initial_state(self) -> None:
        mgr = ConnectionManager()
        assert mgr.active_connections == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_no_connections(self) -> None:
        """Broadcasting with no connections should be a no-op."""
        mgr = ConnectionManager()
        # Should not raise
        await mgr.broadcast({"event": "test"})
