"""
Region-scoped access control for the notifications REST endpoints
(Phase 6) - same approach as test_region_isolation.py/
test_readings_analytics.py: one in-process httpx.AsyncClient(transport=
ASGITransport(...)) scenario, a fresh Motor client per test (see those
files' docstrings for why - motor.AsyncIOMotorClient binds to whichever
event loop first uses it), lifespan never started, all fixture data
tagged "(pytest)" and torn down after.

The live WebSocket push itself (/ws/notifications, notification_rooms.py)
is covered by test_app_notifications.py's unit tests instead of here -
mixing Starlette TestClient's own websocket_connect() (which manages its
own event loop machinery) with this file's asyncio.run() risks
reintroducing the same "Event loop is closed" issue that pattern was
built to avoid.

Run from the repo root:
    .venv\\Scripts\\python.exe -m pytest tests\\test_notifications_api.py -v -s
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

import app
import auth
import database
from config import settings


def _auth_header(user_id: str, username: str, role: str, region_id: str | None) -> dict:
    token = auth.create_access_token(user_id=user_id, username=username, role=role, region_id=region_id)
    return {"Authorization": f"Bearer {token}"}


async def _scenario() -> None:
    transport = ASGITransport(app=app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_id = await database.create_user(
            username="pytest_admin_notif", email="pytest_admin_notif@example.test", password_hash="x", role="admin"
        )
        admin_headers = _auth_header(admin_id, "pytest_admin_notif", "admin", None)
        cleanup_user_ids = [admin_id]
        cleanup_notification_ids: list[str] = []
        region_a_id = region_b_id = factory_a_id = factory_b_id = None

        try:
            region_a_id = await database.create_region("Region A (pytest-notif)", "")
            region_b_id = await database.create_region("Region B (pytest-notif)", "")
            factory_a_id = await database.create_factory("Factory A (pytest-notif)", region_a_id, False, "")
            factory_b_id = await database.create_factory("Factory B (pytest-notif)", region_b_id, False, "")

            head_a_id = await database.create_user(
                username="pytest_head_a_notif", email="pytest_head_a_notif@example.test",
                password_hash="x", role="regional_head", region_id=region_a_id,
            )
            head_b_id = await database.create_user(
                username="pytest_head_b_notif", email="pytest_head_b_notif@example.test",
                password_hash="x", role="regional_head", region_id=region_b_id,
            )
            cleanup_user_ids += [head_a_id, head_b_id]
            head_a_headers = _auth_header(head_a_id, "pytest_head_a_notif", "regional_head", region_a_id)
            head_b_headers = _auth_header(head_b_id, "pytest_head_b_notif", "regional_head", region_b_id)

            notif_a = await database.create_notification(
                region_id=region_a_id, factory_id=factory_a_id, device_id="pytest-device-a",
                co2_value=1250.0, severity="warning", message="pytest-device-a CO2 reading 1250.0 ppm is WARNING",
            )
            notif_b = await database.create_notification(
                region_id=region_b_id, factory_id=factory_b_id, device_id="pytest-device-b",
                co2_value=2600.0, severity="critical", message="pytest-device-b CO2 reading 2600.0 ppm is CRITICAL",
            )
            cleanup_notification_ids += [notif_a["id"], notif_b["id"]]

            # --- 1. regional_head A sees only region A's notification ---
            resp = await client.get("/api/notifications", headers=head_a_headers)
            assert resp.status_code == 200
            ids = {n["id"] for n in resp.json()}
            assert notif_a["id"] in ids
            assert notif_b["id"] not in ids

            # --- 2. regional_head B sees only region B's ---
            resp = await client.get("/api/notifications", headers=head_b_headers)
            assert resp.status_code == 200
            ids = {n["id"] for n in resp.json()}
            assert notif_b["id"] in ids
            assert notif_a["id"] not in ids

            # --- 3. admin sees both by default, and can filter to one region ---
            resp = await client.get("/api/notifications", headers=admin_headers)
            assert resp.status_code == 200
            ids = {n["id"] for n in resp.json()}
            assert {notif_a["id"], notif_b["id"]} <= ids

            resp = await client.get("/api/notifications", params={"region_id": region_a_id}, headers=admin_headers)
            assert resp.status_code == 200
            ids = {n["id"] for n in resp.json()}
            assert notif_a["id"] in ids
            assert notif_b["id"] not in ids

            # --- 4. a regional_head's own region_id query param can't broaden scope ---
            resp = await client.get(
                "/api/notifications", params={"region_id": region_b_id}, headers=head_a_headers
            )
            assert resp.status_code == 200
            ids = {n["id"] for n in resp.json()}
            assert notif_b["id"] not in ids, "region A's head must not see region B's data via a region_id param"

            # --- 5. wrong-region mutation attempts are rejected (404, never data) ---
            resp = await client.post(f"/api/notifications/{notif_a['id']}/seen", headers=head_b_headers)
            assert resp.status_code == 404

            # --- 6. right-region seen/acknowledge work, and unseen=true then excludes it ---
            resp = await client.post(f"/api/notifications/{notif_a['id']}/seen", headers=head_a_headers)
            assert resp.status_code == 200
            assert resp.json()["seen_at"] is not None

            resp = await client.get("/api/notifications", params={"unseen": True}, headers=head_a_headers)
            assert notif_a["id"] not in {n["id"] for n in resp.json()}

            resp = await client.get("/api/notifications", params={"unseen": False}, headers=head_a_headers)
            assert notif_a["id"] in {n["id"] for n in resp.json()}  # still listed once seen, just not "unseen"

            resp = await client.post(f"/api/notifications/{notif_a['id']}/acknowledge", headers=head_a_headers)
            assert resp.status_code == 200
            assert resp.json()["acknowledged"] is True

            print("ALL CHECKS PASSED")
        finally:
            for nid in cleanup_notification_ids:
                try:
                    await database._notifications_collection.delete_one({"_id": database.ObjectId(nid)})
                except Exception as exc:  # noqa: BLE001
                    print(f"teardown warning (notification {nid}): {exc}")
            for uid in cleanup_user_ids:
                try:
                    await database.delete_user(uid)
                except Exception as exc:  # noqa: BLE001
                    print(f"teardown warning (user {uid}): {exc}")
            for fid in (factory_a_id, factory_b_id):
                if fid:
                    try:
                        await database.delete_factory(fid)
                    except Exception as exc:  # noqa: BLE001
                        print(f"teardown warning (factory {fid}): {exc}")
            for rid in (region_a_id, region_b_id):
                if rid:
                    try:
                        await database.delete_region(rid)
                    except Exception as exc:  # noqa: BLE001
                        print(f"teardown warning (region {rid}): {exc}")


async def _mongo_is_reachable() -> bool:
    try:
        await database._client.admin.command("ping")
        return True
    except Exception:
        return False


def test_notifications_region_scoping(monkeypatch):
    fresh_client = AsyncIOMotorClient(settings.mongo_uri)
    fresh_db = fresh_client[settings.mongo_db_name]
    monkeypatch.setattr(database, "_client", fresh_client)
    monkeypatch.setattr(database, "_db", fresh_db)
    monkeypatch.setattr(database, "_collection", fresh_db[database.COLLECTION_NAME])
    monkeypatch.setattr(database, "_users_collection", fresh_db[database.USERS_COLLECTION_NAME])
    monkeypatch.setattr(database, "_regions_collection", fresh_db[database.REGIONS_COLLECTION_NAME])
    monkeypatch.setattr(database, "_factories_collection", fresh_db[database.FACTORIES_COLLECTION_NAME])
    monkeypatch.setattr(database, "_devices_collection", fresh_db[database.DEVICES_COLLECTION_NAME])
    monkeypatch.setattr(database, "_notifications_collection", fresh_db[database.NOTIFICATIONS_COLLECTION_NAME])

    async def _run():
        if not await _mongo_is_reachable():
            pytest.skip("MongoDB is not reachable locally; skipping notifications integration test")
        await _scenario()

    asyncio.run(_run())
