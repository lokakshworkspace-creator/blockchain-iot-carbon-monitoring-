"""
One-off Phase 5 schema migration: creates the users/regions/factories
collections, adds the {device_id, sensor_timestamp} compound index and the
users unique indexes, and backfills factory_id=None onto any existing
sensor_data document that predates this field.

Safe to run more than once - every step here is idempotent (create_index
and create_collection are no-ops if the index/collection already matches;
the backfill only touches documents that are still missing the field).
Does not touch device_id, co2, sensor_timestamp, or hash on any existing
document, so no anchored hash is affected.

Usage (run once, from the Gateway/ directory so config.py finds .env):
    cd Gateway
    python migrate_schema.py
"""

from __future__ import annotations

import asyncio

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING, DESCENDING

from config import settings

SENSOR_COLLECTION = "sensor_data"
NEW_COLLECTIONS = ("users", "regions", "factories")


async def _ensure_collection(db, name: str) -> None:
    existing = await db.list_collection_names()
    if name in existing:
        print(f"  collection {name!r} already exists - skipped")
        return
    await db.create_collection(name)
    print(f"  created collection {name!r}")


async def main() -> None:
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db_name]

    print(f"Connecting to {settings.mongo_uri} / db {settings.mongo_db_name!r}")
    await client.admin.command("ping")
    print("Connected.\n")

    print("1. New collections:")
    for name in NEW_COLLECTIONS:
        await _ensure_collection(db, name)

    print("\n2. users unique indexes:")
    users = db["users"]
    await users.create_index([("username", ASCENDING)], unique=True, name="uniq_username")
    await users.create_index([("email", ASCENDING)], unique=True, name="uniq_email")
    print("  users.username (unique), users.email (unique) ensured")

    print("\n3. sensor_data compound index:")
    sensor_data = db[SENSOR_COLLECTION]
    await sensor_data.create_index(
        [("device_id", ASCENDING), ("sensor_timestamp", DESCENDING)],
        name="device_id_sensor_timestamp",
    )
    print("  {device_id: 1, sensor_timestamp: -1} ensured")

    print("\n4. Backfilling factory_id on existing sensor_data documents:")
    result = await sensor_data.update_many(
        {"factory_id": {"$exists": False}},
        {"$set": {"factory_id": None}},
    )
    print(f"  {result.modified_count} document(s) updated (device_id/co2/sensor_timestamp/hash untouched)")

    print("\nMigration complete.")


if __name__ == "__main__":
    asyncio.run(main())
