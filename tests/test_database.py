"""
Integration test for Gateway/database.py against the real local MongoDB
instance (the same one Gateway/app.py talks to). motor's client is meant to
live for the lifetime of one event loop, so rather than pytest-asyncio's
default per-test event loop (a new one per test would break the
module-level client singleton), this runs every database exercise as a
single asyncio.run() call.

That constraint is why the round trip and the recent-records listing are
phases of one test rather than two test functions: a second asyncio.run()
in this module gets a fresh event loop, leaves the module-level motor
client bound to the dead one, and the test silently skips itself as
"MongoDB unreachable" instead of actually running.
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


async def _insert_retrieve_update_round_trip() -> None:
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


async def _recent_records_listing() -> None:
    inserted = []
    for index in range(3):
        inserted.append(
            await database.insert_sensor_record(
                device_id="test-device-recent",
                co2=float(400 + index),
                sensor_timestamp=f"2026-08-23T00:00:0{index}+00:00",
                gateway_received_timestamp=f"2026-08-23T00:00:0{index}.500000+00:00",
                hash_value=str(index) * 64,
            )
        )
    try:
        records = await database.get_recent_records(limit=3)
        assert len(records) == 3

        # Newest first: the last id inserted must come back first.
        assert records[0]["id"] == inserted[-1]
        assert [record["id"] for record in records] == list(reversed(inserted))

        newest = records[0]
        assert newest["device_id"] == "test-device-recent"
        assert newest["co2"] == 402.0
        assert newest["verification_status"] == "Pending"
        assert newest["blockchain_record_id"] is None
        assert newest["blockchain_tx_hash"] is None

        # Projected away: the list view doesn't need these, and the raw
        # ObjectId is replaced by the string "id" that POST /verify expects.
        assert "hash" not in newest
        assert "gateway_received_timestamp" not in newest
        assert "_id" not in newest

        assert len(await database.get_recent_records(limit=2)) == 2
    finally:
        await database._collection.delete_many({"device_id": "test-device-recent"})


async def _record_counts() -> None:
    # Asserted as deltas, not absolutes: this runs against the real local
    # database, which legitimately holds readings from earlier demo runs.
    before = await database.count_records()

    record_id = await database.insert_sensor_record(
        device_id="test-device-counts",
        co2=500.0,
        sensor_timestamp="2026-08-23T00:00:00+00:00",
        gateway_received_timestamp="2026-08-23T00:00:00.500000+00:00",
        hash_value="c" * 64,
    )
    try:
        after_insert = await database.count_records()
        assert after_insert["total"] == before["total"] + 1
        # Not anchored yet - a fresh record has blockchain_record_id None.
        assert after_insert["anchored"] == before["anchored"]

        await database.update_blockchain_info(record_id, tx_hash="0xfeed", blockchain_record_id=99)

        after_anchor = await database.count_records()
        assert after_anchor["total"] == before["total"] + 1
        assert after_anchor["anchored"] == before["anchored"] + 1
    finally:
        await database._collection.delete_many({"device_id": "test-device-counts"})


def test_database_round_trip_recent_records_and_counts():
    async def _run():
        if not await _mongo_is_reachable():
            pytest.skip("MongoDB is not reachable locally; skipping database.py integration test")

        await _insert_retrieve_update_round_trip()
        await _recent_records_listing()
        await _record_counts()

    asyncio.run(_run())
