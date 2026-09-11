"""
Small helpers shared by the Phase 2 routers. Kept separate from auth.py
(that's Phase 1's, deliberately untouched here) and from database.py
(this raises HTTPException, an HTTP-layer concern - database.py stays
framework-agnostic and raises only bson/pymongo's own errors).
"""

from __future__ import annotations

from bson import ObjectId
from bson.errors import InvalidId
from fastapi import HTTPException, status


def parse_object_id(value: str, field_name: str = "id") -> ObjectId:
    """Every path/body id here arrives as a plain string. ObjectId()
    raises bson.errors.InvalidId (not ValueError) on anything malformed -
    call this first in a route so a bad id is a clean 400, not an
    unhandled 500 from deeper inside database.py."""
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name!r} is not a valid id: {value!r}",
        ) from exc
