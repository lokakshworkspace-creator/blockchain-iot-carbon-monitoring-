"""
Phase 3 tests: GET /api/readings/{device_id} and GET /api/analytics/{device_id}
- chronological ordering, the daily-analytics aggregation's numbers, and
region-scoped access control resolved via devices -> factories.region_id
(not device_id alone).

Same approach and same constraints as test_region_isolation.py: one
in-process httpx.AsyncClient(transport=ASGITransport(...)) scenario, a
fresh Motor client per test (motor.AsyncIOMotorClient binds to whichever
event loop first uses it, so sharing the module-level client across this
file and test_database.py/test_region_isolation.py's own asyncio.run()
calls raises "Event loop is closed" on the second one to run), lifespan
never started, all fixture data tagged "(pytest)" and torn down after.

Run from the repo root:
    .venv\\Scripts\\python.exe -m pytest tests\\test_readings_analytics.py -v -s
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

import app
import auth
import database
from config import settings

DEVICE_ID = "pytest-readings-device"


def _auth_header(user_id: str, username: str, role: str, region_id: str | None) -> dict:
    token = auth.create_access_token(user_id=user_id, username=username, role=role, region_id=region_id)
    return {"Authorization": f"Bearer {token}"}


async def _insert_reading(co2: float, days_ago: int) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return await database.insert_sensor_record(
        device_id=DEVICE_ID,
        co2=co2,
        sensor_timestamp=ts,
        gateway_received_timestamp=ts,
        hash_value="0" * 64,
    )


async def _scenario() -> None:
    transport = ASGITransport(app=app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_id = await database.create_user(
            username="pytest_admin_ra", email="pytest_admin_ra@example.test", password_hash="x", role="admin"
        )
        admin_headers = _auth_header(admin_id, "pytest_admin_ra", "admin", None)
        cleanup_user_ids = [admin_id]
        cleanup_record_ids: list[str] = []

        try:
            # --- fixture readings: today, 2 days ago (below warning), 10 days ago (outside a 7-day window) ---
            warning = settings.co2_warning_threshold
            cleanup_record_ids.append(await _insert_reading(warning + 100, days_ago=0))  # violation, today
            cleanup_record_ids.append(await _insert_reading(warning - 200, days_ago=0))  # normal, today
            cleanup_record_ids.append(await _insert_reading(warning + 50, days_ago=2))  # violation, 2 days ago
            cleanup_record_ids.append(await _insert_reading(warning + 999, days_ago=10))  # outside 7-day window

            # --- 1. GET /api/readings: chronological (oldest first), only this device ---
            resp = await client.get(f"/api/readings/{DEVICE_ID}", headers=admin_headers)
            assert resp.status_code == 200
            rows = resp.json()
            assert len(rows) == 4
            timestamps = [r["sensor_timestamp"] for r in rows]
            assert timestamps == sorted(timestamps), "must be chronological (oldest first), not reversed"
            assert all(r["device_id"] == DEVICE_ID for r in rows)

            # limit is honored
            limited = (await client.get(f"/api/readings/{DEVICE_ID}", params={"limit": 2}, headers=admin_headers)).json()
            assert len(limited) == 2

            # --- 2. GET /api/analytics: grouped by day, threshold_violations against the real configured threshold ---
            resp = await client.get(f"/api/analytics/{DEVICE_ID}", params={"days": 7}, headers=admin_headers)
            assert resp.status_code == 200
            days = resp.json()
            # The 10-days-ago reading must be excluded by the 7-day window.
            total_count = sum(d["count"] for d in days)
            assert total_count == 3, f"expected 3 readings within the 7-day window, got {total_count}"

            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_entry = next(d for d in days if d["date"] == today_str)
            assert today_entry["count"] == 2
            assert today_entry["max"] == warning + 100
            assert today_entry["min"] == warning - 200
            assert today_entry["threshold_violations"] == 1, "only the >= warning-threshold reading counts"

            # --- 3. Unregistered device: regional_head gets 404, never data ---
            head_unreg_id = await database.create_user(
                username="pytest_head_unreg",
                email="pytest_head_unreg@example.test",
                password_hash="x",
                role="regional_head",
                region_id=None,
            )
            cleanup_user_ids.append(head_unreg_id)
            # A regional_head with no region_id at all is an edge case worth covering too -
            # it must never fall through to "no restriction".
            unreg_headers = _auth_header(head_unreg_id, "pytest_head_unreg", "regional_head", None)
            resp = await client.get(f"/api/readings/{DEVICE_ID}", headers=unreg_headers)
            assert resp.status_code == 404

            # --- 4. Registered device: correct region sees it, wrong region gets 404 ---
            region_a_id = await database.create_region("Region A (pytest-ra)", "")
            region_b_id = await database.create_region("Region B (pytest-ra)", "")
            factory_a_id = await database.create_factory("Factory A (pytest-ra)", region_a_id, False, "")
            device_doc_id = await database.create_device(DEVICE_ID, factory_a_id, is_hardware=False)

            head_a_id = await database.create_user(
                username="pytest_head_a_ra",
                email="pytest_head_a_ra@example.test",
                password_hash="x",
                role="regional_head",
                region_id=region_a_id,
            )
            head_b_id = await database.create_user(
                username="pytest_head_b_ra",
                email="pytest_head_b_ra@example.test",
                password_hash="x",
                role="regional_head",
                region_id=region_b_id,
            )
            cleanup_user_ids += [head_a_id, head_b_id]

            head_a_headers = _auth_header(head_a_id, "pytest_head_a_ra", "regional_head", region_a_id)
            head_b_headers = _auth_header(head_b_id, "pytest_head_b_ra", "regional_head", region_b_id)

            resp = await client.get(f"/api/readings/{DEVICE_ID}", headers=head_a_headers)
            assert resp.status_code == 200, "device_id resolves to region A via devices->factories; head A is in region A"
            assert len(resp.json()) == 4

            resp = await client.get(f"/api/readings/{DEVICE_ID}", headers=head_b_headers)
            assert resp.status_code == 404, "head B is a different region - must never see region A's device data"

            resp = await client.get(f"/api/analytics/{DEVICE_ID}", headers=head_b_headers)
            assert resp.status_code == 404, "same restriction must apply to the analytics endpoint"

            # cleanup for this sub-scenario
            await database.delete_device(device_doc_id)
            await database.delete_factory(factory_a_id)
            await database.delete_region(region_a_id)
            await database.delete_region(region_b_id)

            print("ALL CHECKS PASSED")
        finally:
            for record_id in cleanup_record_ids:
                try:
                    await database._collection.delete_one({"_id": database.ObjectId(record_id)})
                except Exception as exc:  # noqa: BLE001
                    print(f"teardown warning (record {record_id}): {exc}")
            for uid in cleanup_user_ids:
                try:
                    await database.delete_user(uid)
                except Exception as exc:  # noqa: BLE001
                    print(f"teardown warning (user {uid}): {exc}")


async def _mongo_is_reachable() -> bool:
    try:
        await database._client.admin.command("ping")
        return True
    except Exception:
        return False


def test_readings_and_analytics_region_scoping(monkeypatch):
    fresh_client = AsyncIOMotorClient(settings.mongo_uri)
    fresh_db = fresh_client[settings.mongo_db_name]
    monkeypatch.setattr(database, "_client", fresh_client)
    monkeypatch.setattr(database, "_db", fresh_db)
    monkeypatch.setattr(database, "_collection", fresh_db[database.COLLECTION_NAME])
    monkeypatch.setattr(database, "_users_collection", fresh_db[database.USERS_COLLECTION_NAME])
    monkeypatch.setattr(database, "_regions_collection", fresh_db[database.REGIONS_COLLECTION_NAME])
    monkeypatch.setattr(database, "_factories_collection", fresh_db[database.FACTORIES_COLLECTION_NAME])
    monkeypatch.setattr(database, "_devices_collection", fresh_db[database.DEVICES_COLLECTION_NAME])

    async def _run():
        if not await _mongo_is_reachable():
            pytest.skip("MongoDB is not reachable locally; skipping readings/analytics integration test")
        await _scenario()

    asyncio.run(_run())
