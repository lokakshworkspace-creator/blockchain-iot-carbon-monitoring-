"""
Chart-hydration and daily-analytics reads (Phase 3), independent of the
live WebSocket feed - GET /api/readings/{device_id} backs the dashboard's
chart-on-load/reconnect, GET /api/analytics/{device_id} backs the "Last 7
Days" panel.

Region-scoped access control, same shape as Phase 2's
GET /api/factories/{id}/devices: applied to BOTH endpoints here, not just
analytics. The request only specified it for analytics, but leaving
/api/readings/{device_id} unscoped would let a regional_head trivially
read another region's raw data through the endpoint analytics is
restricted on - the restriction has to sit on both or it isn't real.

device_id (the MQTT string identity) carries no region information by
itself - resolving it requires the same two-hop lookup Phase 2 built the
devices registry for: device_id -> devices.factory_id -> factories.region_id
(database.get_region_id_for_device()). A device that isn't registered in
that collection at all resolves to no region, which for a regional_head
means "out of scope" (404), never a default-allow. An admin never goes
through this check - {} is always their filter, as in every other Phase 2
route.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status

from auth import CurrentUser, get_current_user
from config import settings
from database import get_daily_analytics, get_readings, get_region_id_for_device
from models import AnalyticsDayItem, ReadingItem

router = APIRouter(prefix="/api", tags=["readings"])

# Same reasoning as app.py's MAX_RECORDS_LIMIT: a generous cap so a stray
# large request can't pull an unbounded number of documents into memory
# and stall the event loop.
DEFAULT_READINGS_LIMIT = 500
MAX_READINGS_LIMIT = 1000
DEFAULT_ANALYTICS_DAYS = 7
MAX_ANALYTICS_DAYS = 90


async def _ensure_device_in_scope(device_id: str, current_user: CurrentUser) -> None:
    """404 (not 403), matching routers/factories.py's reasoning: the
    "isn't registered to any region" and "belongs to another region"
    cases are indistinguishable to the caller by design, so a regional_head
    can't use the response to fingerprint which device_ids exist
    elsewhere."""
    if current_user.role == "admin":
        return
    device_region_id = await get_region_id_for_device(device_id)
    if device_region_id is None or device_region_id != current_user.region_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")


@router.get("/readings/{device_id}", response_model=list[ReadingItem])
async def readings(
    device_id: str,
    limit: int = Query(DEFAULT_READINGS_LIMIT, ge=1, le=MAX_READINGS_LIMIT),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    await _ensure_device_in_scope(device_id, current_user)
    return await get_readings(device_id, limit)


@router.get("/analytics/{device_id}", response_model=list[AnalyticsDayItem])
async def analytics(
    device_id: str,
    days: int = Query(DEFAULT_ANALYTICS_DAYS, ge=1, le=MAX_ANALYTICS_DAYS),
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict]:
    await _ensure_device_in_scope(device_id, current_user)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return await get_daily_analytics(device_id, cutoff, settings.co2_warning_threshold)
