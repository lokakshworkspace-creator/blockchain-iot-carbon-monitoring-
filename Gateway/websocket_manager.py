"""
Tracks connected dashboard WebSocket clients and broadcasts messages to all
of them. This is Pipeline A's delivery mechanism: threshold/device-status
events get pushed here and fanned out, never blocking on any one slow client.
"""

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)
        logger.info("WebSocket connected (%d total)", len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(websocket)
        logger.info("WebSocket disconnected (%d total)", len(self._connections))

    async def broadcast(self, message: dict) -> None:
        async with self._lock:
            targets = list(self._connections)

        for websocket in targets:
            try:
                await websocket.send_json(message)
            except Exception:
                logger.warning("Failed to send to a WebSocket client, dropping it", exc_info=True)
                async with self._lock:
                    self._connections.discard(websocket)


manager = WebSocketManager()
