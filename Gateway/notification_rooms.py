"""
Region-scoped WebSocket rooms for the notifications feature (Phase 6) -
separate from websocket_manager.py's broadcast-to-everyone /ws, which
stays exactly as it is (see routers/notifications.py's module docstring
for why this is a new endpoint rather than a retrofit of /ws).

One in-memory mapping, region_id -> set of connected websockets, held in
this single FastAPI process - no external pub/sub, matching this
project's stated preference for minimal moving parts and the fact this
is one process. An admin connection joins a single sentinel room
(_ADMIN_ROOM) rather than every individual region's room, so it
automatically covers regions created after the admin connected without
tracking membership changes.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import WebSocket

logger = logging.getLogger(__name__)

# Not a real region_id (those are Mongo ObjectId hex strings, a fixed
# 24 hex chars) - collision with an actual region is not possible.
ADMIN_ROOM = "__admin__"


class NotificationRooms:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    @staticmethod
    def room_for(role: str, region_id: str | None) -> str | None:
        """The room a connecting user belongs in - ADMIN_ROOM for an
        admin, their own region_id for a regional_head, or None if a
        regional_head has no region_id at all (nothing sensible to join;
        the caller should refuse the connection)."""
        if role == "admin":
            return ADMIN_ROOM
        return region_id

    async def join(self, websocket: WebSocket, room: str) -> None:
        async with self._lock:
            self._rooms.setdefault(room, set()).add(websocket)
            size = len(self._rooms[room])
        logger.info("Notification socket joined room %s (%d in room)", room, size)

    async def leave(self, websocket: WebSocket, room: str) -> None:
        async with self._lock:
            sockets = self._rooms.get(room)
            if sockets is None:
                return
            sockets.discard(websocket)
            if not sockets:
                del self._rooms[room]

    async def send_to_region(self, region_id: str, message: dict) -> bool:
        """Pushes to the region's own room plus the admin room (admins
        see every region's alerts, per the room design above). Returns
        whether at least one socket actually received it - the caller
        uses this to decide the notification's delivered_realtime flag,
        so it reflects an attempted, real delivery, not just "a room
        happened to exist"."""
        async with self._lock:
            targets = set(self._rooms.get(region_id, ())) | set(self._rooms.get(ADMIN_ROOM, ()))
        if not targets:
            return False

        delivered = False
        for websocket in targets:
            try:
                await websocket.send_json(message)
                delivered = True
            except Exception:
                logger.warning("Failed to send to a notification WebSocket client, dropping it", exc_info=True)
                async with self._lock:
                    for room_sockets in self._rooms.values():
                        room_sockets.discard(websocket)
        return delivered


rooms = NotificationRooms()
