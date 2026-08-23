"""
Integration test for Gateway/database.py against the real local MongoDB
instance (the same one Gateway/app.py talks to). motor's client is meant to
live for the lifetime of one event loop, so rather than pytest-asyncio's
default per-test event loop (a new one per test would break the
module-level client singleton), this runs the whole insert -> retrieve ->
update round trip as a single asyncio.run() call. Skips itself if MongoDB
isn't reachable, rather than failing the whole suite.
"""

import asyncio

import pytest

import database


async def _mongo_is_reachable() -> bool:
    try:
        await database._client.admin.command("ping")
        return True
    except Exception:
        return False


def test_insert_retrieve_and_update_round_trip():
    async def _run():
        if not await _mongo_is_reachable():
            pytest.skip("MongoDB is not reachable locally; skipping database.py integration test")

        record_id = await database.insert_sensor_record(
            device_id="test-device",
            co2=812.3,
            sensor_timestamp="2026-08-23T00:00:00+00:00",
            gateway_received_timestamp="2026-08-23T00:00:00.500000+00:00",
            hash_value="a" * 64,
        )
        try:
            assert record_id

            record = await database.get_sensor_record(record_id)
            assert record is not None
            assert record["device_id"] == "test-device"
            assert record["co2"] == 812.3
            assert record["hash"] == "a" * 64
            assert record["verification_status"] == "Pending"
            assert record["blockchain_tx_hash"] is None
            assert record["blockchain_record_id"] is None

            await database.update_blockchain_info(record_id, tx_hash="0xabc123", blockchain_record_id=7)
            await database.update_verification_status(record_id, status="Verified")

            updated = await database.get_sensor_record(record_id)
            assert updated["blockchain_tx_hash"] == "0xabc123"
            assert updated["blockchain_record_id"] == 7
            assert updated["verification_status"] == "Verified"

            missing = await database.get_sensor_record("0" * 24)
            assert missing is None
        finally:
            # Don't leave test documents behind in the real local database.
            await database._collection.delete_one({"_id": database.ObjectId(record_id)})

    asyncio.run(_run())
