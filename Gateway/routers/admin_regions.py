"""
Admin-only CRUD for regions (Phase 2). Every route requires the admin role
via require_role("admin") - regions sit at the top of the
region -> factory -> device hierarchy, so only an admin ever creates or
removes one; a regional_head only ever reads their own via
GET /api/regions/me (routers/regions.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from auth import CurrentUser, require_role
from database import (
    count_factories_in_region,
    create_region,
    delete_region,
    get_region,
    list_regions,
    update_region,
)
from models import RegionCreate, RegionItem, RegionUpdate
from routers._common import parse_object_id

router = APIRouter(prefix="/api/admin/regions", tags=["admin:regions"])


@router.post("", response_model=RegionItem, status_code=status.HTTP_201_CREATED)
async def create(body: RegionCreate, _admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    region_id = await create_region(body.name, body.description)
    return await get_region(region_id)


@router.get("", response_model=list[RegionItem])
async def list_all(_admin: CurrentUser = Depends(require_role("admin"))) -> list[dict]:
    return await list_regions()


@router.get("/{region_id}", response_model=RegionItem)
async def get_one(region_id: str, _admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    parse_object_id(region_id, "region_id")
    region = await get_region(region_id)
    if region is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Region not found")
    return region


@router.patch("/{region_id}", response_model=RegionItem)
async def update(
    region_id: str, body: RegionUpdate, _admin: CurrentUser = Depends(require_role("admin"))
) -> dict:
    parse_object_id(region_id, "region_id")
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    matched = await update_region(region_id, updates)
    if not matched:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Region not found")
    return await get_region(region_id)


@router.delete("/{region_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(region_id: str, _admin: CurrentUser = Depends(require_role("admin"))) -> None:
    parse_object_id(region_id, "region_id")
    in_use = await count_factories_in_region(region_id)
    if in_use > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete: {in_use} factory(ies) still reference this region",
        )
    deleted = await delete_region(region_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Region not found")
