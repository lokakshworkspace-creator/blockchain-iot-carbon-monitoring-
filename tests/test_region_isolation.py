"""
Phase 2 region-isolation tests: proves a regional_head token cannot read
another region's factories/devices, and spot-checks the admin-only routes
and the "second admin" create guard.

Runs entirely in-process against the real FastAPI app object via
httpx.AsyncClient(transport=ASGITransport(...)) - no live gateway process
needed, and the app's lifespan (MQTT bridge, blockchain client) is never
invoked this way (ASGITransport calls the app's request handlers directly;
lifespan is a separate event this test never sends), so this cannot
collide with a gateway that's already running for a demo, and never
touches Sepolia.

It DOES use the real MongoDB from Gateway/.env, since that's what proves
the Mongo-level filtering actually works - all fixture data is tagged
"(pytest)" and removed in teardown regardless of outcome.

Everything (Motor calls and HTTP-style calls alike) runs on ONE asyncio
event loop via a single asyncio.run() - motor.AsyncIOMotorClient binds to
whichever loop it's first used on, so spreading calls across several
separate asyncio.run() invocations (each with its own loop) raises
"RuntimeError: Event loop is closed" on the second one (see
test_database.py's docstring - same constraint, same reason). Hence one
test function, not nine - the granularity trade-off is worth the
reliability here.

Setup bypasses the API only for the first admin (mints its JWT directly
via auth.create_access_token(), the same way create_admin.py's own
account gets in) specifically so this file carries no dependency on
knowing the real bootstrap admin's password. Everything downstream goes
through the real HTTP endpoints.

Run from the repo root:
    .venv\\Scripts\\python.exe -m pytest tests\\test_region_isolation.py -v -s
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

import app  # sys.path is set up by conftest.py
import auth
import database
from config import settings


async def _mongo_is_reachable() -> bool:
    try:
        await database._client.admin.command("ping")
        return True
    except Exception:
        return False


def _auth_header(user_id: str, username: str, role: str, region_id: str | None) -> dict:
    token = auth.create_access_token(user_id=user_id, username=username, role=role, region_id=region_id)
    return {"Authorization": f"Bearer {token}"}


async def _scenario() -> None:
    transport = ASGITransport(app=app.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin_id = await database.create_user(
            username="pytest_admin_ri",
            email="pytest_admin_ri@example.test",
            password_hash=auth.hash_password("not-used-directly"),
            role="admin",
        )
        admin_headers = _auth_header(admin_id, "pytest_admin_ri", "admin", None)
        cleanup_user_ids = [admin_id]

        try:
            region_a = (
                await client.post("/api/admin/regions", json={"name": "Region A (pytest)"}, headers=admin_headers)
            ).json()
            region_b = (
                await client.post("/api/admin/regions", json={"name": "Region B (pytest)"}, headers=admin_headers)
            ).json()

            factory_a = (
                await client.post(
                    "/api/admin/factories",
                    json={"name": "Factory A (pytest)", "region_id": region_a["id"]},
                    headers=admin_headers,
                )
            ).json()
            factory_b = (
                await client.post(
                    "/api/admin/factories",
                    json={"name": "Factory B (pytest)", "region_id": region_b["id"]},
                    headers=admin_headers,
                )
            ).json()

            head_resp = await client.post(
                "/api/admin/users",
                json={
                    "username": "pytest_head_a",
                    "email": "pytest_head_a@example.test",
                    "password": "pytestPass123!",
                    "role": "regional_head",
                    "region_id": region_a["id"],
                },
                headers=admin_headers,
            )
            assert head_resp.status_code == 201, head_resp.text
            cleanup_user_ids.append(head_resp.json()["id"])

            login_resp = await client.post(
                "/api/auth/login", json={"username": "pytest_head_a", "password": "pytestPass123!"}
            )
            assert login_resp.status_code == 200, login_resp.text
            head_a_headers = {"Authorization": f"Bearer {login_resp.json()['access_token']}"}

            # --- 1. GET /api/factories: regional_head sees only their own region ---
            resp = await client.get("/api/factories", headers=head_a_headers)
            assert resp.status_code == 200
            ids = {f["id"] for f in resp.json()}
            assert factory_a["id"] in ids, "regional_head should see their own region's factory"
            assert factory_b["id"] not in ids, "regional_head must NOT see another region's factory"

            # --- 2. GET /api/factories/{other region's id}/devices: 404, never data ---
            resp = await client.get(f"/api/factories/{factory_b['id']}/devices", headers=head_a_headers)
            assert resp.status_code == 404, "another region's factory_id must not resolve for this caller"
            assert resp.json() == {"detail": "Factory not found"}

            # --- 3. GET /api/factories/{own factory}/devices: 200, in-scope ---
            resp = await client.get(f"/api/factories/{factory_a['id']}/devices", headers=head_a_headers)
            assert resp.status_code == 200
            assert resp.json() == []

            # --- 4. GET /api/regions/me: regional_head gets a single object, their own ---
            resp = await client.get("/api/regions/me", headers=head_a_headers)
            assert resp.status_code == 200
            body = resp.json()
            assert isinstance(body, dict) and body["id"] == region_a["id"]

            # --- 5. GET /api/regions/me: admin gets the full list ---
            resp = await client.get("/api/regions/me", headers=admin_headers)
            assert resp.status_code == 200
            admin_region_ids = {r["id"] for r in resp.json()}
            assert {region_a["id"], region_b["id"]} <= admin_region_ids

            # --- 6. GET /api/factories: admin sees every region's factories ---
            resp = await client.get("/api/factories", headers=admin_headers)
            assert resp.status_code == 200
            admin_factory_ids = {f["id"] for f in resp.json()}
            assert {factory_a["id"], factory_b["id"]} <= admin_factory_ids

            # --- 7. regional_head is refused on admin-only routes ---
            resp = await client.get("/api/admin/regions", headers=head_a_headers)
            assert resp.status_code == 403

            # --- 8. no token at all is refused ---
            resp = await client.get("/api/factories")
            assert resp.status_code == 401

            # --- 9. creating a second admin requires the confirm flag ---
            no_flag = await client.post(
                "/api/admin/users",
                json={
                    "username": "pytest_admin_2",
                    "email": "pytest_admin_2@example.test",
                    "password": "pytestPass123!",
                    "role": "admin",
                },
                headers=admin_headers,
            )
            assert no_flag.status_code == 400, "creating role=admin without confirm_admin_creation must be rejected"

            with_flag = await client.post(
                "/api/admin/users",
                json={
                    "username": "pytest_admin_2",
                    "email": "pytest_admin_2@example.test",
                    "password": "pytestPass123!",
                    "role": "admin",
                    "confirm_admin_creation": True,
                },
                headers=admin_headers,
            )
            assert with_flag.status_code == 201, with_flag.text
            cleanup_user_ids.append(with_flag.json()["id"])

            print("ALL CHECKS PASSED")
        finally:
            # Teardown: users -> factories -> regions, so nothing is left
            # orphaned. Independent try/excepts so one already-gone document
            # doesn't stop the rest from being cleaned up.
            for uid in cleanup_user_ids:
                try:
                    await database.delete_user(uid)
                except Exception as exc:  # noqa: BLE001
                    print(f"teardown warning (user {uid}): {exc}")
            for fid in (locals().get("factory_a", {}).get("id"), locals().get("factory_b", {}).get("id")):
                if fid:
                    try:
                        await database.delete_factory(fid)
                    except Exception as exc:  # noqa: BLE001
                        print(f"teardown warning (factory {fid}): {exc}")
            for rid in (locals().get("region_a", {}).get("id"), locals().get("region_b", {}).get("id")):
                if rid:
                    try:
                        await database.delete_region(rid)
                    except Exception as exc:  # noqa: BLE001
                        print(f"teardown warning (region {rid}): {exc}")


def test_region_isolation_and_admin_guards(monkeypatch):
    # A fresh Motor client, scoped to this test's own asyncio.run() loop.
    # Reusing the module-level database._client would risk it having
    # already been bound (by an earlier test file's own asyncio.run() call
    # in the same pytest session, e.g. test_database.py) to a loop that's
    # since closed - motor.AsyncIOMotorClient stays bound to whichever
    # loop it was first used on, so a second, different loop trying to use
    # the same client hits "Event loop is closed" or silently reads as
    # unreachable. This sidesteps that by never sharing a client across
    # test files' separate event loops.
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
            pytest.skip("MongoDB is not reachable locally; skipping region-isolation integration test")
        await _scenario()

    asyncio.run(_run())
