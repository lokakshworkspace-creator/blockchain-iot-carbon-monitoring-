"""
Pydantic response models for the gateway's REST endpoints.

This is a typing/validation layer over response shapes app.py already
builds and returns correctly - it changes no behavior. Used as
response_model= on each endpoint in app.py, which gets three things for
free: FastAPI validates the real return value actually matches the
declared shape (so a future accidental extra/missing field is a loud
error, not a silent wire-format drift), any field genuinely not part of
the declared model is stripped from the response, and /docs generates a
real, accurate OpenAPI schema instead of an untyped "any object".

Every field here mirrors an existing dict shape exactly - see
database.py, device_status.py, and verification.py for where each one is
actually built. Every endpoint through Phase 4 took no JSON body (record_id
is a path parameter, limit is a query parameter); POST /api/auth/login
(Phase 5) is the first to need a request-body model, hence LoginRequest
below alongside the response models.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """GET /health - see app.py's health()."""

    status: str
    mqtt_broker: str
    mqtt_topic: str
    co2_warning_threshold: float
    co2_critical_threshold: float


class DeviceStatusItem(BaseModel):
    """One entry in GET /devices/status - see
    device_status.py's DeviceStatusTracker.snapshot()."""

    device_id: str
    online: bool
    last_seen: str  # ISO 8601, e.g. "2026-08-24T06:12:27.975061+00:00"


class RecordItem(BaseModel):
    """One entry in GET /records - see database.py's
    get_recent_records() and its _RECENT_RECORDS_PROJECTION.

    blockchain_record_id/blockchain_tx_hash are always present as keys
    (None until a reading is anchored - see insert_sensor_record()).
    last_auto_verified_at is genuinely absent from the underlying
    document until scheduler.py's mark_auto_verified() first touches a
    record, hence the default rather than a bare annotation.
    """

    id: str
    device_id: str
    co2: float
    sensor_timestamp: str
    verification_status: str
    blockchain_record_id: int | None
    blockchain_tx_hash: str | None
    last_auto_verified_at: str | None = None


class RecordsStatsResponse(BaseModel):
    """GET /records/stats - see database.py's count_records()."""

    total: int
    anchored: int


class VerifyResponse(BaseModel):
    """POST /verify/{record_id} - see verification.py's verify_record().
    stored_hash/onchain_hash/recomputed_hash are None wherever the
    corresponding value was never available (e.g. NotFound has none of
    the three; NotAnchored has stored_hash but not the other two) - see
    verify_record()'s five return branches for exactly which fields are
    populated for each status.
    """

    status: Literal["Verified", "Tampered", "NotAnchored", "NotFound", "Error"]
    stored_hash: str | None
    onchain_hash: str | None
    recomputed_hash: str | None


class LoginRequest(BaseModel):
    """POST /api/auth/login request body - see auth.py's authenticate_user()."""

    username: str
    password: str


class LoginResponse(BaseModel):
    """POST /api/auth/login - see app.py's login(). role/region_id are
    duplicated here (they're also inside access_token's JWT claims) purely
    so the dashboard can render "logged in as <role>" without decoding the
    token client-side."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in_hours: int
    role: str
    region_id: str | None


# --- Phase 2: regions/factories/devices/users admin CRUD + region-scoped reads ---


class RegionCreate(BaseModel):
    name: str
    description: str = ""


class RegionUpdate(BaseModel):
    """All fields optional - a PATCH only touches whatever the caller
    actually included in the body (see routers/_common.py's exclude_unset
    usage)."""

    name: str | None = None
    description: str | None = None


class RegionItem(BaseModel):
    id: str
    name: str
    description: str
    created_at: str


class FactoryCreate(BaseModel):
    name: str
    region_id: str
    is_simulated: bool = False
    location: str = ""


class FactoryUpdate(BaseModel):
    name: str | None = None
    region_id: str | None = None
    is_simulated: bool | None = None
    location: str | None = None


class FactoryItem(BaseModel):
    id: str
    name: str
    region_id: str
    is_simulated: bool
    location: str
    created_at: str


class DeviceCreate(BaseModel):
    """device_id is the MQTT identity (matches sensor_data.device_id);
    factory_id is this registry document's parent factory."""

    device_id: str
    factory_id: str
    is_hardware: bool = False


class DeviceUpdate(BaseModel):
    device_id: str | None = None
    factory_id: str | None = None
    is_hardware: bool | None = None


class DeviceItem(BaseModel):
    id: str
    device_id: str
    factory_id: str
    is_hardware: bool
    created_at: str


class AdminUserCreate(BaseModel):
    """POST /api/admin/users. confirm_admin_creation must be explicitly
    true to create role="admin" - see routers/admin_users.py's module
    docstring for why. Ignored entirely for role="regional_head"."""

    username: str
    email: str
    password: str
    role: Literal["admin", "regional_head"]
    region_id: str | None = None
    confirm_admin_creation: bool = False


class AdminUserUpdate(BaseModel):
    """PATCH /api/admin/users/{id}. Deliberately no role or password field
    here - see routers/admin_users.py's module docstring for why role
    changes aren't part of this endpoint."""

    region_id: str | None = None
    is_active: bool | None = None


class UserItem(BaseModel):
    id: str
    username: str
    email: str
    role: str
    region_id: str | None
    is_active: bool
    created_at: str
    last_login: str | None
