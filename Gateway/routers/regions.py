"""
GET /api/regions/me (Phase 2): the calling user's own region for a
regional_head, or every region for an admin. Deliberately the only region
read available to a regional_head with no id parameter at all - there is
nothing here for a regional_head to manipulate into reading someone
else's region, unlike /api/factories/{factory_id}/devices which does take
one (and enforces scope on it via region_scope_filter there instead).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from auth import CurrentUser, get_current_user
from database import get_region, list_regions
from models import RegionItem

router = APIRouter(prefix="/api/regions", tags=["regions"])


@router.get("/me", response_model=RegionItem | list[RegionItem])
async def my_region(current_user: CurrentUser = Depends(get_current_user)):
    if current_user.role == "admin":
        return await list_regions()

    if current_user.region_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No region assigned to this account")
    region = await get_region(current_user.region_id)
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assigned region no longer exists")
    return region
