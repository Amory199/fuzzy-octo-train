"""WebSocket connection manager for real-time event streaming.

Broadcasts workflow and task lifecycle events to connected dashboard
clients.  Integrates with the existing :class:`EventBus` by subscribing
to all event types and forwarding them as JSON over WebSocket.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

logger = logging.getLogger(__name__)


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.append(ws)
        logger.info("WebSocket client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self._connections:
            self._connections.remove(ws)
        logger.info("WebSocket client disconnected (%d total)", len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send *data* as JSON to every connected client."""
        if not self._connections:
            return
        message = json.dumps(data, default=str)
        stale: list[WebSocket] = []
        for ws in self._connections:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(message)
            except (WebSocketDisconnect, RuntimeError):
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)

    @property
    def active_connections(self) -> int:
        return len(self._connections)
