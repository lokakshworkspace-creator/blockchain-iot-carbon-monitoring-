"""
Tests for POST /api/auth/change-password (the self-service password change
added alongside the login-gated landing page): a correct current_password
+ a valid new_password succeeds and the new password actually works on a
subsequent login; a wrong current_password is rejected and changes
nothing; and there is no way for one account to change another's password
- the endpoint takes no user_id, only ever acting on the caller's own
account via their token.

Same conventions as test_region_isolation.py (see that file's docstring
for the full rationale): in-process against the real FastAPI app via
httpx.ASGITransport (no live gateway process, no lifespan/MQTT/blockchain
involvement), against the real MongoDB from Gateway/.env (needed to prove
the actual stored password_hash changes), one asyncio.run() for the whole
scenario (Motor binds to whichever loop first uses it), fixtures tagged
"(pytest)"/pytest_ prefixed and torn down in a finally regardless of
outcome, and the first admin's JWT minted directly via
auth.create_access_token() rather than depending on the real bootstrap
admin's password.

Run from the repo root:
    .venv\\Scripts\\python.exe -m pytest tests\\test_change_password.py -v -s
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
            username="pytest_admin_cp",
            email="pytest_admin_cp@example.test",
            password_hash=auth.hash_password("not-used-directly"),
            role="admin",
        )
        admin_headers = _auth_header(admin_id, "pytest_admin_cp", "admin", None)
        cleanup_user_ids = [admin_id]

        try:
            # Two regular accounts, both created with a known starting
            # password via the real admin API (not directly via
            # database.create_user, so this test exercises the same
            # password_hash the real signup path produces).
            user_a = await client.post(
                "/api/admin/users",
                json={
                    "username": "pytest_cp_user_a",
                    "email": "pytest_cp_user_a@example.test",
                    "password": "OriginalPass123!",
                    "role": "admin",
                    "confirm_admin_creation": True,
                },
                headers=admin_headers,
            )
            assert user_a.status_code == 201, user_a.text
            user_a_id = user_a.json()["id"]
            cleanup_user_ids.append(user_a_id)

            user_b = await client.post(
                "/api/admin/users",
                json={
                    "username": "pytest_cp_user_b",
                    "email": "pytest_cp_user_b@example.test",
                    "password": "UntouchedPass123!",
                    "role": "admin",
                    "confirm_admin_creation": True,
                },
                headers=admin_headers,
            )
            assert user_b.status_code == 201, user_b.text
            user_b_id = user_b.json()["id"]
            cleanup_user_ids.append(user_b_id)

            login_a = await client.post(
                "/api/auth/login", json={"username": "pytest_cp_user_a", "password": "OriginalPass123!"}
            )
            assert login_a.status_code == 200, login_a.text
            a_token = login_a.json()["access_token"]
            a_headers = {"Authorization": f"Bearer {a_token}"}

            # --- 1. Wrong current_password: rejected, nothing changes.
            # 400, not 401 - the caller's token is valid (that's what
            # a_headers proves), it's the current_password field that's
            # wrong, a plain bad-input case. See app.py's change_password()
            # docstring: using 401 here was tried and caught by a real
            # browser test, since the frontend's global 401 interceptor
            # (services/api.js) treats ANY 401 as "session over, log out" -
            # which would silently log the user out on a mistyped
            # password, the opposite of what should happen. ---
            resp = await client.post(
                "/api/auth/change-password",
                json={"current_password": "TotallyWrongPassword!", "new_password": "NewPassword123!"},
                headers=a_headers,
            )
            assert resp.status_code == 400, resp.text

            # The token itself must still be treated as valid after this -
            # a 401 here would mean the interceptor bug is back.
            resp = await client.get("/api/admin/regions", headers=a_headers)
            assert resp.status_code == 200, "a wrong-current-password rejection must not invalidate the caller's token"

            # The original password must still work - a rejected attempt
            # must not have touched the stored hash.
            relogin = await client.post(
                "/api/auth/login", json={"username": "pytest_cp_user_a", "password": "OriginalPass123!"}
            )
            assert relogin.status_code == 200, "a failed change-password attempt must not alter the password"

            # --- 2. new_password too short: rejected at the request-body
            # validation level (min_length=8), password still unchanged ---
            resp = await client.post(
                "/api/auth/change-password",
                json={"current_password": "OriginalPass123!", "new_password": "short1"},
                headers=a_headers,
            )
            assert resp.status_code == 422, resp.text

            # --- 3. Correct current_password + valid new_password: succeeds ---
            resp = await client.post(
                "/api/auth/change-password",
                json={"current_password": "OriginalPass123!", "new_password": "NewPassword123!"},
                headers=a_headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.json() == {"success": True}

            # The OLD password must no longer work...
            old_login = await client.post(
                "/api/auth/login", json={"username": "pytest_cp_user_a", "password": "OriginalPass123!"}
            )
            assert old_login.status_code == 401, "the old password must stop working after a successful change"

            # ...and the NEW password must actually work on a fresh login.
            new_login = await client.post(
                "/api/auth/login", json={"username": "pytest_cp_user_a", "password": "NewPassword123!"}
            )
            assert new_login.status_code == 200, new_login.text

            # --- 4. No token reissue required: the ORIGINAL token from
            # step 0's login (minted before the password change) must
            # still authorize requests - per the brief, the existing
            # session is not invalidated by a password change. ---
            resp = await client.get("/api/admin/regions", headers=a_headers)
            assert resp.status_code == 200, "the pre-change token must remain valid after a password change"

            # --- 5. Cross-account isolation: user A changing their own
            # password must never affect user B. There is no user_id field
            # on the request at all - the endpoint can only ever act on
            # whoever the caller's own token identifies. ---
            b_still_works = await client.post(
                "/api/auth/login", json={"username": "pytest_cp_user_b", "password": "UntouchedPass123!"}
            )
            assert b_still_works.status_code == 200, "user A's password change must not affect user B's password"

            print("ALL CHECKS PASSED")
        finally:
            for uid in cleanup_user_ids:
                try:
                    await database.delete_user(uid)
                except Exception as exc:  # noqa: BLE001
                    print(f"teardown warning (user {uid}): {exc}")


def test_change_password(monkeypatch):
    # Fresh Motor client bound to this test's own asyncio.run() loop - see
    # test_region_isolation.py's test function docstring for why sharing
    # database._client across test files' separate loops breaks.
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
            pytest.skip("MongoDB is not reachable locally; skipping change-password integration test")
        await _scenario()

    asyncio.run(_run())
