"""
Admin-only CRUD for the device registry (Phase 2): links an MQTT device_id
to a factory, plus an is_hardware flag distinguishing real ESP32 nodes
from tests/mqtt_test_publisher.py simulations. This is a separate concept
from sensor_data (which records what a device reported) - this is the
registry of what devices exist and which factory they belong to. The path
parameter is device_doc_id (this registry document's Mongo _id), not
device_id (the MQTT string identity), so the two never get confused in a
URL like /api/admin/devices/{device_doc_id}.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from auth import CurrentUser, require_role
from database import (
    create_device,
    delete_device,
    get_device,
    get_factory,
    list_devices,
    update_device,
)
from models import DeviceCreate, DeviceItem, DeviceUpdate
from routers._common import parse_object_id

router = APIRouter(prefix="/api/admin/devices", tags=["admin:devices"])


async def _require_factory_exists(factory_id: str) -> None:
    parse_object_id(factory_id, "factory_id")
    if await get_factory(factory_id) is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"No such factory: {factory_id!r}")


@router.post("", response_model=DeviceItem, status_code=status.HTTP_201_CREATED)
async def create(body: DeviceCreate, _admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    await _require_factory_exists(body.factory_id)
    try:
        device_doc_id = await create_device(body.device_id, body.factory_id, body.is_hardware)
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"device_id {body.device_id!r} is already registered",
        ) from exc
    return await get_device(device_doc_id)


@router.get("", response_model=list[DeviceItem])
async def list_all(_admin: CurrentUser = Depends(require_role("admin"))) -> list[dict]:
    return await list_devices()


@router.get("/{device_doc_id}", response_model=DeviceItem)
async def get_one(device_doc_id: str, _admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    parse_object_id(device_doc_id)
    device = await get_device(device_doc_id)
    if device is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return device


@router.patch("/{device_doc_id}", response_model=DeviceItem)
async def update(
    device_doc_id: str, body: DeviceUpdate, _admin: CurrentUser = Depends(require_role("admin"))
) -> dict:
    parse_object_id(device_doc_id)
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")
    if updates.get("factory_id") is not None:
        await _require_factory_exists(updates["factory_id"])
    try:
        matched = await update_device(device_doc_id, updates)
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="device_id is already registered to another device",
        ) from exc
    if not matched:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
    return await get_device(device_doc_id)


@router.delete("/{device_doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(device_doc_id: str, _admin: CurrentUser = Depends(require_role("admin"))) -> None:
    parse_object_id(device_doc_id)
    deleted = await delete_device(device_doc_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Device not found")
