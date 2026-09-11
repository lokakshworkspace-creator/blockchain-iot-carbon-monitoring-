"""
Async MongoDB layer (Pipeline B) via motor. Stores one document per sensor
reading in the sensor_data collection: the raw reading fields, the SHA-256
hash from hashing.py, and a verification_status that starts "Pending".
blockchain.py (once built) will fill in the tx info via
update_blockchain_info() after a Sepolia transaction confirms.

Phase 5 adds three schema-only collections for the auth/RBAC layer (users,
regions, factories) and an optional factory_id on sensor_data. factory_id
is metadata only - it is never read by hashing.py, and adding it here does
not touch the hash inputs (device_id, co2, sensor_timestamp) at all.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import DESCENDING

from config import settings

COLLECTION_NAME = "sensor_data"
USERS_COLLECTION_NAME = "users"
REGIONS_COLLECTION_NAME = "regions"
FACTORIES_COLLECTION_NAME = "factories"
DEVICES_COLLECTION_NAME = "devices"

_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_uri)
_db = _client[settings.mongo_db_name]
_collection = _db[COLLECTION_NAME]
_users_collection = _db[USERS_COLLECTION_NAME]
_regions_collection = _db[REGIONS_COLLECTION_NAME]
_factories_collection = _db[FACTORIES_COLLECTION_NAME]
_devices_collection = _db[DEVICES_COLLECTION_NAME]


def _to_api_dict(document: dict[str, Any], *object_id_fields: str) -> dict[str, Any]:
    """Common conversion for documents returned over the API: renames _id
    to id (both as str) and stringifies any other ObjectId-valued fields
    named in object_id_fields (e.g. region_id, factory_id) - Mongo's
    ObjectId isn't JSON-serializable and every reference field here holds
    one as-is."""
    document = dict(document)
    document["id"] = str(document.pop("_id"))
    for field_name in object_id_fields:
        if document.get(field_name) is not None:
            document[field_name] = str(document[field_name])
    return document


async def insert_sensor_record(
    device_id: str,
    co2: float,
    sensor_timestamp: str,
    gateway_received_timestamp: str,
    hash_value: str,
    factory_id: str | None = None,
) -> str:
    """Insert one sensor reading with verification_status="Pending" and no
    blockchain info yet. Returns the new document's MongoDB _id as a str.

    factory_id is optional and unrelated to the hash: hashing.generate_hash()
    is called by the caller (app.py's Pipeline B) with only device_id, co2,
    and sensor_timestamp, before this function ever runs. No router wires a
    real factory_id through yet, so today's callers all pass None here -
    the field exists on the schema so a later phase doesn't need another
    migration."""
    document = {
        "device_id": device_id,
        "co2": co2,
        "sensor_timestamp": sensor_timestamp,
        "gateway_received_timestamp": gateway_received_timestamp,
        "hash": hash_value,
        "verification_status": "Pending",
        "blockchain_tx_hash": None,
        "blockchain_record_id": None,
        "factory_id": ObjectId(factory_id) if factory_id else None,
    }
    result = await _collection.insert_one(document)
    return str(result.inserted_id)


async def get_sensor_record(record_id: str) -> dict[str, Any] | None:
    document = await _collection.find_one({"_id": ObjectId(record_id)})
    if document is None:
        return None
    document["_id"] = str(document["_id"])
    return document


# The subset of fields the dashboard's record list needs. `hash` and
# gateway_received_timestamp are deliberately left out: the list view never
# shows them, and verification.py re-reads the full document by id anyway.
# last_auto_verified_at is included so the dashboard COULD show "last
# auto-verified at" later without a new endpoint - absent entirely on any
# record the scheduler hasn't touched yet, per mark_auto_verified() below.
_RECENT_RECORDS_PROJECTION = {
    "device_id": 1,
    "co2": 1,
    "sensor_timestamp": 1,
    "verification_status": 1,
    "blockchain_record_id": 1,
    "blockchain_tx_hash": 1,
    "last_auto_verified_at": 1,
}


async def get_recent_records(limit: int) -> list[dict[str, Any]]:
    """Most recent sensor readings, newest first, for the dashboard's
    Verification and Blockchain Logs pages.

    Sorted by _id rather than sensor_timestamp: _id is monotonic in
    insertion order and indexed by default, whereas sensor_timestamp comes
    from the device's own clock - which is neither guaranteed monotonic
    across devices nor indexed here.
    """
    cursor = _collection.find({}, _RECENT_RECORDS_PROJECTION).sort("_id", -1).limit(limit)
    records = []
    async for document in cursor:
        # Exposed as "id" (a str) rather than a raw ObjectId, matching what
        # insert_sensor_record returns and what POST /verify/{id} expects.
        document["id"] = str(document.pop("_id"))
        records.append(document)
    return records


async def count_records() -> dict[str, int]:
    """Collection-level counts for the dashboard's Overview tiles.

    count_documents() rather than fetching rows and counting them in the
    browser: Overview only needs two integers, and pulling the collection
    across the wire to derive them would get slower with every reading the
    demo produces.
    """
    total = await _collection.count_documents({})
    anchored = await _collection.count_documents({"blockchain_record_id": {"$ne": None}})
    return {"total": total, "anchored": anchored}


async def get_recently_anchored_records(limit: int) -> list[dict[str, Any]]:
    """The most recently anchored records - blockchain_record_id set,
    newest first - for scheduler.py's periodic re-verification sample.

    Only the id is projected: verify_record() re-fetches the full
    document itself via get_sensor_record(), so this just needs to name
    which records are worth spending a cycle on. Filtering to
    blockchain_record_id != None skips records verify_record() would
    immediately report NotAnchored for anyway - no point spending a
    scheduled check on a record with nothing on-chain to compare against.
    """
    cursor = (
        _collection.find({"blockchain_record_id": {"$ne": None}}, {"_id": 1}).sort("_id", -1).limit(limit)
    )
    return [{"id": str(document["_id"])} async for document in cursor]


async def mark_auto_verified(record_id: str) -> None:
    """Stamps when scheduler.py last automatically re-checked this
    record. Deliberately separate from verification_status (which
    verify_record() itself owns and which a manual check updates too) -
    this field answers "was this auto-checked, and when", not "what did
    the check find". A manual POST /verify/{id} call never touches this;
    only scheduler.py does.
    """
    await _collection.update_one(
        {"_id": ObjectId(record_id)},
        {"$set": {"last_auto_verified_at": datetime.now(timezone.utc).isoformat()}},
    )


async def update_blockchain_info(record_id: str, tx_hash: str, blockchain_record_id: int) -> None:
    await _collection.update_one(
        {"_id": ObjectId(record_id)},
        {"$set": {"blockchain_tx_hash": tx_hash, "blockchain_record_id": blockchain_record_id}},
    )


async def update_verification_status(record_id: str, status: str) -> None:
    await _collection.update_one(
        {"_id": ObjectId(record_id)},
        {"$set": {"verification_status": status}},
    )


# --- Phase 5: users/regions/factories (auth.py, create_admin.py) ---


async def get_user_by_username(username: str) -> dict[str, Any] | None:
    """Looks up a user for login. Includes password_hash (auth.py needs it
    to verify the login attempt) - callers must strip it before returning
    anything derived from this document over the API."""
    document = await _users_collection.find_one({"username": username})
    if document is None:
        return None
    document["_id"] = str(document["_id"])
    if document.get("region_id") is not None:
        document["region_id"] = str(document["region_id"])
    return document


async def create_user(
    username: str,
    email: str,
    password_hash: str,
    role: str,
    region_id: str | None = None,
) -> str:
    """Inserts one user document. Raises pymongo.errors.DuplicateKeyError
    if username or email already exists (see migrate_schema.py's unique
    indexes) - callers (create_admin.py today) should let that surface
    rather than silently overwrite an existing account."""
    document = {
        "username": username,
        "email": email,
        "password_hash": password_hash,
        "role": role,
        "region_id": ObjectId(region_id) if region_id else None,
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login": None,
    }
    result = await _users_collection.insert_one(document)
    return str(result.inserted_id)


async def touch_last_login(user_id: str) -> None:
    """Stamps last_login on a successful POST /api/auth/login. Best-effort:
    callers should not fail the login itself if this write has a problem."""
    await _users_collection.update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"last_login": datetime.now(timezone.utc).isoformat()}},
    )


async def get_user_by_id(user_id: str) -> dict[str, Any] | None:
    """Public-facing single-user lookup (GET/PATCH/DELETE /api/admin/users/{id})
    - password_hash is excluded at the query level, not left to
    response_model filtering alone, so this dict is safe to return even
    before pydantic sees it."""
    document = await _users_collection.find_one({"_id": ObjectId(user_id)}, {"password_hash": 0})
    if document is None:
        return None
    return _to_api_dict(document, "region_id")


async def list_users() -> list[dict[str, Any]]:
    cursor = _users_collection.find({}, {"password_hash": 0}).sort("_id", -1)
    return [_to_api_dict(document, "region_id") async for document in cursor]


async def update_user(user_id: str, updates: dict[str, Any]) -> bool:
    """updates comes from AdminUserUpdate.model_dump(exclude_unset=True) -
    today that's only region_id and is_active (see models.py for why role
    is deliberately not patchable here)."""
    doc_updates = dict(updates)
    if "region_id" in doc_updates:
        doc_updates["region_id"] = ObjectId(doc_updates["region_id"]) if doc_updates["region_id"] else None
    result = await _users_collection.update_one({"_id": ObjectId(user_id)}, {"$set": doc_updates})
    return result.matched_count > 0


async def delete_user(user_id: str) -> bool:
    result = await _users_collection.delete_one({"_id": ObjectId(user_id)})
    return result.deleted_count > 0


async def count_active_admins() -> int:
    """Used by the admin_users router to refuse deleting/deactivating the
    last remaining admin - with no open registration endpoint, losing the
    last one would be unrecoverable short of going back to
    create_admin.py directly against MongoDB."""
    return await _users_collection.count_documents({"role": "admin", "is_active": True})


# --- Phase 2: regions/factories/devices CRUD (admin_*.py, factories.py, regions.py routers) ---


async def create_region(name: str, description: str) -> str:
    document = {
        "name": name,
        "description": description,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await _regions_collection.insert_one(document)
    return str(result.inserted_id)


async def get_region(region_id: str) -> dict[str, Any] | None:
    document = await _regions_collection.find_one({"_id": ObjectId(region_id)})
    if document is None:
        return None
    return _to_api_dict(document)


async def list_regions() -> list[dict[str, Any]]:
    cursor = _regions_collection.find({}).sort("_id", -1)
    return [_to_api_dict(document) async for document in cursor]


async def update_region(region_id: str, updates: dict[str, Any]) -> bool:
    result = await _regions_collection.update_one({"_id": ObjectId(region_id)}, {"$set": updates})
    return result.matched_count > 0


async def delete_region(region_id: str) -> bool:
    result = await _regions_collection.delete_one({"_id": ObjectId(region_id)})
    return result.deleted_count > 0


async def count_factories_in_region(region_id: str) -> int:
    """Guards DELETE /api/admin/regions/{id}: a region with factories still
    pointing at it is left alone rather than silently orphaning them."""
    return await _factories_collection.count_documents({"region_id": ObjectId(region_id)})


async def create_factory(name: str, region_id: str, is_simulated: bool, location: str) -> str:
    document = {
        "name": name,
        "region_id": ObjectId(region_id),
        "is_simulated": is_simulated,
        "location": location,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await _factories_collection.insert_one(document)
    return str(result.inserted_id)


async def get_factory(factory_id: str) -> dict[str, Any] | None:
    document = await _factories_collection.find_one({"_id": ObjectId(factory_id)})
    if document is None:
        return None
    return _to_api_dict(document, "region_id")


async def get_factory_scoped(factory_id: str, scope_filter: dict[str, Any]) -> dict[str, Any] | None:
    """Like get_factory(), but ANDs scope_filter (auth.region_scope_filter()'s
    output) into the same query - the existence check and the region check
    are one Mongo call, so a regional_head requesting another region's
    factory_id gets exactly the same "not found" result as a genuinely
    nonexistent id. There is no separate step where a 403 could leak
    "it exists, just not for you"."""
    query: dict[str, Any] = {"_id": ObjectId(factory_id), **scope_filter}
    document = await _factories_collection.find_one(query)
    if document is None:
        return None
    return _to_api_dict(document, "region_id")


async def list_factories(scope_filter: dict[str, Any]) -> list[dict[str, Any]]:
    """scope_filter is auth.region_scope_filter()'s output - {} for an
    admin (no restriction), {"region_id": ObjectId(...)} for a
    regional_head. The restriction is applied inside this Mongo query,
    not by filtering an unrestricted fetch afterward."""
    cursor = _factories_collection.find(scope_filter).sort("_id", -1)
    return [_to_api_dict(document, "region_id") async for document in cursor]


async def update_factory(factory_id: str, updates: dict[str, Any]) -> bool:
    doc_updates = dict(updates)
    if "region_id" in doc_updates and doc_updates["region_id"] is not None:
        doc_updates["region_id"] = ObjectId(doc_updates["region_id"])
    result = await _factories_collection.update_one({"_id": ObjectId(factory_id)}, {"$set": doc_updates})
    return result.matched_count > 0


async def delete_factory(factory_id: str) -> bool:
    result = await _factories_collection.delete_one({"_id": ObjectId(factory_id)})
    return result.deleted_count > 0


async def count_devices_in_factory(factory_id: str) -> int:
    """Guards DELETE /api/admin/factories/{id}, same reasoning as
    count_factories_in_region()."""
    return await _devices_collection.count_documents({"factory_id": ObjectId(factory_id)})


async def create_device(device_id: str, factory_id: str, is_hardware: bool) -> str:
    """Raises pymongo.errors.DuplicateKeyError if device_id is already
    registered - see migrate_schema.py's unique index on devices.device_id."""
    document = {
        "device_id": device_id,
        "factory_id": ObjectId(factory_id),
        "is_hardware": is_hardware,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    result = await _devices_collection.insert_one(document)
    return str(result.inserted_id)


async def get_device(device_doc_id: str) -> dict[str, Any] | None:
    document = await _devices_collection.find_one({"_id": ObjectId(device_doc_id)})
    if document is None:
        return None
    return _to_api_dict(document, "factory_id")


async def list_devices() -> list[dict[str, Any]]:
    cursor = _devices_collection.find({}).sort("_id", -1)
    return [_to_api_dict(document, "factory_id") async for document in cursor]


async def list_devices_by_factory(factory_id: str) -> list[dict[str, Any]]:
    """No extra region check needed here - the caller (routers/factories.py)
    only reaches this after get_factory_scoped() has already confirmed the
    factory itself is in the caller's scope, and every device belongs to
    exactly one factory."""
    cursor = _devices_collection.find({"factory_id": ObjectId(factory_id)}).sort("_id", -1)
    return [_to_api_dict(document, "factory_id") async for document in cursor]


async def update_device(device_doc_id: str, updates: dict[str, Any]) -> bool:
    """Raises pymongo.errors.DuplicateKeyError if updates changes device_id
    to one that's already registered to a different device."""
    doc_updates = dict(updates)
    if "factory_id" in doc_updates and doc_updates["factory_id"] is not None:
        doc_updates["factory_id"] = ObjectId(doc_updates["factory_id"])
    result = await _devices_collection.update_one({"_id": ObjectId(device_doc_id)}, {"$set": doc_updates})
    return result.matched_count > 0


async def delete_device(device_doc_id: str) -> bool:
    result = await _devices_collection.delete_one({"_id": ObjectId(device_doc_id)})
    return result.deleted_count > 0


async def get_region_id_for_device(device_id: str) -> str | None:
    """Resolves an MQTT device_id (the string identity, not a Mongo _id)
    to its region, via the devices registry (Phase 2) -> factories.region_id
    - device_id alone carries no region information, so this two-hop
    lookup is required rather than optional. Returns None if the device
    isn't registered, or its factory no longer exists - callers
    (routers/readings.py) treat that as "cannot be proven to belong to
    any region", which for a regional_head means out of scope, never a
    default-allow."""
    device = await _devices_collection.find_one({"device_id": device_id})
    if device is None:
        return None
    factory = await _factories_collection.find_one({"_id": device["factory_id"]})
    if factory is None:
        return None
    return str(factory["region_id"])


# --- Phase 3: chart-hydration reads (routers/readings.py) ---


async def get_readings(device_id: str, limit: int) -> list[dict[str, Any]]:
    """Most recent `limit` readings for one device, sorted by
    sensor_timestamp descending then reversed here so the caller gets
    chronological (oldest-first) order - what a chart's x-axis needs.
    Sorted by sensor_timestamp (not _id, unlike get_recent_records) since
    that function merges every device together where insertion order
    matters more than device-local time; this is scoped to one device_id,
    where the device's own reported time is the more meaningful axis."""
    cursor = (
        _collection.find({"device_id": device_id}, {"_id": 0, "device_id": 1, "co2": 1, "sensor_timestamp": 1})
        .sort("sensor_timestamp", DESCENDING)
        .limit(limit)
    )
    rows = [row async for row in cursor]
    rows.reverse()
    return rows


async def get_daily_analytics(device_id: str, cutoff_iso: str, warning_threshold: float) -> list[dict[str, Any]]:
    """Per-day CO2 stats for one device over [cutoff_iso, now]. sensor_timestamp
    is stored as an ISO-8601 string (per CLAUDE.md's canonical hash fields,
    this is never touched), so $dateFromString parses it before grouping
    by calendar day - a plain string $substr would work today only because
    every writer in this codebase happens to use the same fixed-width
    isoformat(), which is a much more fragile thing to depend on.

    threshold_violations counts readings at or above co2_warning_threshold
    (the same boundary threshold.py's _classify() uses for "not NORMAL") -
    the existing alert threshold, not a new one invented for this endpoint."""
    pipeline = [
        {"$match": {"device_id": device_id, "sensor_timestamp": {"$gte": cutoff_iso}}},
        {"$addFields": {"_ts": {"$dateFromString": {"dateString": "$sensor_timestamp"}}}},
        {
            "$group": {
                "_id": {"$dateToString": {"format": "%Y-%m-%d", "date": "$_ts"}},
                "avg": {"$avg": "$co2"},
                "min": {"$min": "$co2"},
                "max": {"$max": "$co2"},
                "count": {"$sum": 1},
                "threshold_violations": {"$sum": {"$cond": [{"$gte": ["$co2", warning_threshold]}, 1, 0]}},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    results = []
    async for doc in _collection.aggregate(pipeline):
        results.append(
            {
                "date": doc["_id"],
                "avg": round(doc["avg"], 1),
                "min": doc["min"],
                "max": doc["max"],
                "count": doc["count"],
                "threshold_violations": doc["threshold_violations"],
            }
        )
    return results
