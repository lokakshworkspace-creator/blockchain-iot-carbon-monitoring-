"""
Admin-only CRUD for factories (Phase 2). region_id is required on create
and validated against the regions collection on both create and update -
a factory pointing at a nonexistent region is a data-integrity bug this
endpoint refuses to create, not something left to surface later.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from auth import CurrentUser, require_role
from database import (
    count_devices_in_factory,
    create_factory,
    delete_factory,
    get_factory,
    get_region,
    list_factories,
    update_factory,
)
from models import FactoryCreate, FactoryItem, FactoryUpdate
from routers._common import parse_object_id

router = APIRouter(prefix="/api/admin/factories", tags=["admin:factories"])


async def _require_region_exists(region_id: str) -> None:
    parse_object_id(region_id, "region_id")
    if await get_region(region_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"No such region: {region_id!r}")


@router.post("", response_model=FactoryItem, status_code=status.HTTP_201_CREATED)
async def create(body: FactoryCreate, _admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    await _require_region_exists(body.region_id)
    factory_id = await create_factory(body.name, body.region_id, body.is_simulated, body.location)
    return await get_factory(factory_id)


@router.get("", response_model=list[FactoryItem])
async def list_all(_admin: CurrentUser = Depends(require_role("admin"))) -> list[dict]:
    """Every factory, any region - the admin-only equivalent of
    GET /api/factories (routers/factories.py), which is region-scoped."""
    return await list_factories({})


@router.get("/{factory_id}", response_model=FactoryItem)
async def get_one(factory_id: str, _admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    parse_object_id(factory_id, "factory_id")
    factory = await get_factory(factory_id)
    if factory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factory not found")
    return factory


@router.patch("/{factory_id}", response_model=FactoryItem)
async def update(
    factory_id: str, body: FactoryUpdate, _admin: CurrentUser = Depends(require_role("admin"))
) -> dict:
    parse_object_id(factory_id, "factory_id")
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    if updates.get("region_id") is not None:
        await _require_region_exists(updates["region_id"])
    matched = await update_factory(factory_id, updates)
    if not matched:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factory not found")
    return await get_factory(factory_id)


@router.delete("/{factory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(factory_id: str, _admin: CurrentUser = Depends(require_role("admin"))) -> None:
    parse_object_id(factory_id, "factory_id")
    in_use = await count_devices_in_factory(factory_id)
    if in_use > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot delete: {in_use} device(s) still reference this factory",
        )
    deleted = await delete_factory(factory_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factory not found")
