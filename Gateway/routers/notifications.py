"""
Notifications (Phase 6): a persistent, region-scoped record of every
WARNING/CRITICAL threshold alert, plus a live push to whoever's
connected. Two delivery paths for the same event, by design - a
dashboard that's open right now gets it instantly over WebSocket; one
that isn't finds it waiting in GET /api/notifications on next login.

WS /ws/notifications is a NEW, separate endpoint from the existing
app.py /ws - deliberately, not a retrofit. /ws is unauthenticated and
used by every dashboard page today (Overview, Real-Time Data, System
Monitor) for the general live event feed; the dashboard still has no
real login page (Phase 3's noted gap - only a manual devtools-console
token workaround), so requiring auth on /ws itself would break every
other page today. This endpoint is purely additive: /ws is untouched.

Region rooms (notification_rooms.py) are a second, independent
in-memory structure from websocket_manager.py's single broadcast-to-all
set - intentionally not unified, since one is "everyone gets
everything" and the other is "only this region (and admins) gets this."
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status

from auth import CurrentUser, decode_access_token, get_current_user, region_scope_filter
from database import (
    get_notification,
    list_notifications,
    mark_notification_acknowledged,
    mark_notification_seen,
)
from models import NotificationItem
from notification_rooms import rooms
from routers._common import parse_object_id

router = APIRouter(prefix="/api", tags=["notifications"])

# Separate, un-prefixed router just for the websocket route: an
# APIRouter's prefix applies to every route added to it, including
# @router.websocket(), so a "/ws/notifications" path declared on the
# prefixed router above would actually register at "/api/ws/notifications"
# - caught by testing this against a real client before shipping it (see
# the Phase 6 commit). This keeps it a sibling of the existing /ws
# (app.py), not nested under /api, matching that precedent.
ws_router = APIRouter(tags=["notifications"])

DEFAULT_LIST_LIMIT = 50
MAX_LIST_LIMIT = 200


async def _ensure_notification_in_scope(notification_id: str, current_user: CurrentUser) -> dict:
    """404 (not 403) for another region's notification, same reasoning as
    every other region-scoped lookup in this codebase (routers/factories.py,
    routers/readings.py): "doesn't exist" and "exists, but not for you"
    must be indistinguishable to the caller."""
    notification = await get_notification(notification_id)
    if notification is None or (
        current_user.role != "admin" and notification["region_id"] != current_user.region_id
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notification


@router.get("/notifications", response_model=list[NotificationItem])
async def list_notifications_endpoint(
    unseen: bool = Query(True),
    region_id: str | None = Query(None, description="Admin only - defaults to every region."),
    limit: int = Query(DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    if current_user.role == "admin":
        scope = {}
        if region_id is not None:
            scope = {"region_id": parse_object_id(region_id, "region_id")}
    else:
        # A regional_head's own region always wins - any region_id they
        # pass is ignored rather than honored, so this can't be used to
        # broaden scope beyond region_scope_filter()'s own restriction.
        scope = region_scope_filter(current_user)

    return await list_notifications(scope, unseen_only=unseen, limit=limit)


@router.post("/notifications/{notification_id}/seen", response_model=NotificationItem)
async def mark_seen(notification_id: str, current_user: CurrentUser = Depends(get_current_user)) -> dict:
    parse_object_id(notification_id, "notification_id")
    await _ensure_notification_in_scope(notification_id, current_user)
    await mark_notification_seen(notification_id)
    return await get_notification(notification_id)


@router.post("/notifications/{notification_id}/acknowledge", response_model=NotificationItem)
async def acknowledge(notification_id: str, current_user: CurrentUser = Depends(get_current_user)) -> dict:
    parse_object_id(notification_id, "notification_id")
    await _ensure_notification_in_scope(notification_id, current_user)
    await mark_notification_acknowledged(notification_id)
    return await get_notification(notification_id)


@ws_router.websocket("/ws/notifications")
async def notifications_ws(websocket: WebSocket) -> None:
    """Auth via query param (?token=<jwt>), not an Authorization header -
    the browser WebSocket API has no way to set custom headers on the
    handshake, but a query param is trivial from both sides. Rejection
    happens by calling close() BEFORE accept() - verified against a real
    client (websockets, not just Starlette's TestClient) that this makes
    the handshake itself fail with a plain HTTP 403, rather than the
    client observing a successful upgrade that then immediately closes.
    The specific 4401/4403 codes passed to close() are for server-side
    log/test visibility only; a real client sees a bare 403 either way,
    by design - it never gets to believe it's subscribed."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return

    try:
        current_user = decode_access_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return

    room = rooms.room_for(current_user.role, current_user.region_id)
    if room is None:
        # A regional_head with no region_id at all - nothing sensible to
        # subscribe them to.
        await websocket.close(code=4403)
        return

    await websocket.accept()
    await rooms.join(websocket, room)
    try:
        while True:
            # Receive-only client, same pattern as app.py's /ws - this
            # only exists to detect a disconnect (a closed socket raises
            # WebSocketDisconnect here).
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await rooms.leave(websocket, room)
