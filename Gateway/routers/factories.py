"""
Region-scoped factory reads, available to both roles (Phase 2). The
restriction that keeps a regional_head from seeing another region's data
happens inside the Mongo query itself - auth.region_scope_filter() builds
that filter and database.py's list_factories()/get_factory_scoped() apply
it as part of the query - never by fetching everything and filtering in
Python afterward, and never left to the frontend.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from auth import CurrentUser, get_current_user, region_scope_filter
from database import get_factory_scoped, list_devices_by_factory, list_factories
from models import DeviceItem, FactoryItem
from routers._common import parse_object_id

router = APIRouter(prefix="/api/factories", tags=["factories"])


@router.get("", response_model=list[FactoryItem])
async def list_mine(current_user: CurrentUser = Depends(get_current_user)) -> list[dict]:
    """Every factory for an admin; only the caller's own region's
    factories for a regional_head."""
    return await list_factories(region_scope_filter(current_user))


@router.get("/{factory_id}/devices", response_model=list[DeviceItem])
async def devices_for_factory(
    factory_id: str, current_user: CurrentUser = Depends(get_current_user)
) -> list[dict]:
    """404 (not 403) for a factory outside the caller's region - the scope
    check and the existence check are the same Mongo query
    (get_factory_scoped), so "wrong region" and "doesn't exist" are
    indistinguishable to the caller by design. That's strictly safer than
    a 403, which would confirm the factory exists somewhere."""
    parse_object_id(factory_id, "factory_id")
    factory = await get_factory_scoped(factory_id, region_scope_filter(current_user))
    if factory is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Factory not found")
    return await list_devices_by_factory(factory_id)
