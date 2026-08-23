"""
Async MongoDB layer (Pipeline B) via motor. Stores one document per sensor
reading in the sensor_data collection: the raw reading fields, the SHA-256
hash from hashing.py, and a verification_status that starts "Pending".
blockchain.py (once built) will fill in the tx info via
update_blockchain_info() after a Sepolia transaction confirms.
"""

from __future__ import annotations

from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from config import settings

COLLECTION_NAME = "sensor_data"

_client: AsyncIOMotorClient = AsyncIOMotorClient(settings.mongo_uri)
_collection = _client[settings.mongo_db_name][COLLECTION_NAME]


async def insert_sensor_record(
    device_id: str,
    co2: float,
    sensor_timestamp: str,
    gateway_received_timestamp: str,
    hash_value: str,
) -> str:
    """Insert one sensor reading with verification_status="Pending" and no
    blockchain info yet. Returns the new document's MongoDB _id as a str."""
    document = {
        "device_id": device_id,
        "co2": co2,
        "sensor_timestamp": sensor_timestamp,
        "gateway_received_timestamp": gateway_received_timestamp,
        "hash": hash_value,
        "verification_status": "Pending",
        "blockchain_tx_hash": None,
        "blockchain_record_id": None,
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
_RECENT_RECORDS_PROJECTION = {
    "device_id": 1,
    "co2": 1,
    "sensor_timestamp": 1,
    "verification_status": 1,
    "blockchain_record_id": 1,
    "blockchain_tx_hash": 1,
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
