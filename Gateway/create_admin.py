"""
One-off CLI to create the first admin user. There is no UI or open
registration endpoint by design (RBAC only has two roles, and only an
admin can be expected to create further accounts later) - so the very
first account has to be created out-of-band, here.

Run migrate_schema.py first so the users collection's unique indexes on
username/email exist before this inserts anything.

Usage (run from the Gateway/ directory so config.py finds .env):
    cd Gateway
    python create_admin.py --username admin --email admin@example.com
    (prompts for a password if --password is omitted, so it never ends up
    in shell history)

    # or, non-interactively:
    python create_admin.py --username admin --email admin@example.com --password "..."
"""

from __future__ import annotations

import argparse
import asyncio
import getpass

from pymongo.errors import DuplicateKeyError

from auth import hash_password
from database import create_user


async def _create(username: str, email: str, password: str) -> None:
    password_hash = hash_password(password)
    try:
        user_id = await create_user(
            username=username,
            email=email,
            password_hash=password_hash,
            role="admin",
            region_id=None,  # admins are not scoped to a region, per the schema
        )
    except DuplicateKeyError as exc:
        raise SystemExit(
            f"Could not create user: username {username!r} or email {email!r} already exists."
        ) from exc

    print(f"Admin user created: username={username!r} email={email!r} id={user_id}")
    print("Log in with POST /api/auth/login to get a JWT.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first admin user (one-off, out-of-band).")
    parser.add_argument("--username", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--password",
        default=None,
        help="If omitted, you'll be prompted (hidden input) instead - avoids the password landing in shell history.",
    )
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password for the new admin: ")
    if not password:
        raise SystemExit("Password cannot be empty.")

    asyncio.run(_create(args.username, args.email, password))


if __name__ == "__main__":
    main()
