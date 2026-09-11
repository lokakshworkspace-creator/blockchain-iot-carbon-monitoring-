"""
Admin-only CRUD for user accounts (Phase 2): create Regional Head accounts,
reassign a regional_head's region, deactivate/reactivate, or remove an
account outright. There is still no open registration endpoint - this is
the only way any account past the first (create_admin.py) ever gets
created.

Two safety rules sit on top of plain CRUD, both deliberate:
- Creating a second admin through this endpoint requires
  confirm_admin_creation=true in the request body. Without it, role="admin"
  is rejected with a 400 - a mistyped role field should never silently
  mint another admin.
- The system may never end up with zero active admins: deleting or
  deactivating (is_active=false) the last one is rejected. With no
  registration endpoint, losing the last admin would be unrecoverable
  short of going back to create_admin.py directly against MongoDB.

Role is deliberately not part of AdminUserUpdate (models.py) - there is no
"promote to admin" via PATCH, specifically so the confirm_admin_creation
guard above can't be bypassed by creating a regional_head and then
PATCHing its role.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pymongo.errors import DuplicateKeyError

from auth import CurrentUser, hash_password, require_role
from database import (
    count_active_admins,
    create_user,
    delete_user,
    get_region,
    get_user_by_id,
    list_users,
    update_user,
)
from models import AdminUserCreate, AdminUserUpdate, UserItem
from routers._common import parse_object_id

router = APIRouter(prefix="/api/admin/users", tags=["admin:users"])


@router.post("", response_model=UserItem, status_code=status.HTTP_201_CREATED)
async def create(body: AdminUserCreate, _admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    if body.role == "admin":
        if not body.confirm_admin_creation:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Creating an admin account requires confirm_admin_creation=true",
            )
        region_id = None  # admins are never region-scoped, per the Phase 1 schema
    else:
        if not body.region_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="regional_head accounts require region_id"
            )
        parse_object_id(body.region_id, "region_id")
        if await get_region(body.region_id) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"No such region: {body.region_id!r}"
            )
        region_id = body.region_id

    try:
        user_id = await create_user(
            username=body.username,
            email=body.email,
            password_hash=hash_password(body.password),
            role=body.role,
            region_id=region_id,
        )
    except DuplicateKeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"username {body.username!r} or email {body.email!r} already exists",
        ) from exc
    return await get_user_by_id(user_id)


@router.get("", response_model=list[UserItem])
async def list_all(_admin: CurrentUser = Depends(require_role("admin"))) -> list[dict]:
    return await list_users()


@router.get("/{user_id}", response_model=UserItem)
async def get_one(user_id: str, _admin: CurrentUser = Depends(require_role("admin"))) -> dict:
    parse_object_id(user_id, "user_id")
    user = await get_user_by_id(user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/{user_id}", response_model=UserItem)
async def update(
    user_id: str, body: AdminUserUpdate, _admin: CurrentUser = Depends(require_role("admin"))
) -> dict:
    parse_object_id(user_id, "user_id")
    target = await get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if updates.get("region_id") is not None:
        if target["role"] == "admin":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Admins cannot be assigned a region"
            )
        parse_object_id(updates["region_id"], "region_id")
        if await get_region(updates["region_id"]) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"No such region: {updates['region_id']!r}"
            )

    if updates.get("is_active") is False and target["role"] == "admin" and await count_active_admins() <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate the last remaining admin"
        )

    await update_user(user_id, updates)
    return await get_user_by_id(user_id)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(user_id: str, _admin: CurrentUser = Depends(require_role("admin"))) -> None:
    parse_object_id(user_id, "user_id")
    target = await get_user_by_id(user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target["role"] == "admin" and await count_active_admins() <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete the last remaining admin"
        )
    await delete_user(user_id)
