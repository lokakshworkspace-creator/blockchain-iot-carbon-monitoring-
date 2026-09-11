"""
JWT auth for the Phase 5 RBAC layer: password hashing (bcrypt), token
issuance/validation, and the two FastAPI dependencies routers use to gate
access - get_current_user and require_role(). Independent of both
pipelines: nothing here touches threshold.py, blockchain.py, hashing.py,
or the MQTT consumer, and no existing route is modified by this module.

Design choice worth noting: get_current_user only decodes and validates
the JWT itself (signature, expiry, shape) - it does not re-fetch the user
from MongoDB on every request. That keeps auth stateless and cheap, and
matches "short expiry (8h), no refresh-token complexity" from the spec.
The tradeoff: deactivating a user (is_active=False) or changing their role
takes effect on their next login, not mid-session - accepted here given
the 8h expiry and capstone scale, not an oversight.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt
from bson import ObjectId
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ValidationError

from config import settings
from database import get_user_by_username

_JWT_ALGORITHM = "HS256"

# auto_error=False so a missing/malformed Authorization header reaches our
# own 401 below (with a message and WWW-Authenticate header) instead of
# FastAPI's default, less specific error.
_bearer_scheme = HTTPBearer(auto_error=False)


class CurrentUser(BaseModel):
    """Decoded JWT claims for the authenticated request - not a fresh DB
    read, see the module docstring for why. role is a plain str (not a
    Literal) so a decode never fails on it; require_role() below is what
    actually enforces which roles are meaningful."""

    user_id: str
    username: str
    role: str
    region_id: str | None


def hash_password(password: str) -> str:
    """bcrypt caps input at 72 bytes; this project's passwords are typed by
    a handful of known users, not attacker-controlled, so bcrypt's own
    silent truncation past that is an accepted limitation here rather than
    something worth adding extra validation for."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def create_access_token(user_id: str, username: str, role: str, region_id: str | None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "username": username,
        "role": role,
        "region_id": region_id,
        "iat": now,
        "exp": now + timedelta(hours=settings.jwt_expiry_hours),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_JWT_ALGORITHM)


def _decode_token(token: str) -> CurrentUser:
    try:
        payload: dict[str, Any] = jwt.decode(token, settings.jwt_secret_key, algorithms=[_JWT_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    try:
        return CurrentUser(
            user_id=payload["user_id"],
            username=payload["username"],
            role=payload["role"],
            region_id=payload.get("region_id"),
        )
    except (KeyError, ValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token") from exc


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> CurrentUser:
    """FastAPI dependency: `current_user: CurrentUser = Depends(get_current_user)`
    on any route that requires a logged-in user, any role."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return _decode_token(credentials.credentials)


def require_role(role: str):
    """Dependency factory: `Depends(require_role("admin"))` on a route
    restricts it to that exact role. Two roles exist today (admin,
    regional_head), so this is a plain equality check, not a hierarchy -
    admin does not implicitly satisfy a require_role("regional_head")
    route, since none exists yet that would need that."""

    async def _dependency(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if current_user.role != role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"This action requires the '{role}' role",
            )
        return current_user

    return _dependency


def region_scope_filter(current_user: CurrentUser) -> dict:
    """Mongo filter to merge into any region-scoped query. Admins see
    everything (empty filter, i.e. no restriction); a regional_head sees
    only documents tagged with their own region_id. Centralized here so
    every future router applies the same rule instead of each
    reimplementing "admin sees all, regional_head sees theirs"."""
    if current_user.role == "admin":
        return {}
    return {"region_id": ObjectId(current_user.region_id) if current_user.region_id else None}


async def authenticate_user(username: str, password: str) -> dict[str, Any] | None:
    """Looks up the user, checks is_active, verifies the password. Returns
    the user document (region_id already stringified by get_user_by_username)
    on success, None on any failure - POST /api/auth/login turns a None
    into one generic 401 so a caller can't distinguish "no such user" from
    "wrong password"."""
    user = await get_user_by_username(username)
    if user is None:
        return None
    if not user.get("is_active", False):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user
