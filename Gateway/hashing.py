"""
SHA-256 hashing for tamper-evident sensor records. The canonical string is
built from device_id + co2 + sensor_timestamp ONLY, per CLAUDE.md -
gateway_received_timestamp is never part of the hash. generate_hash() is
the single function called at both write time (database.py, when a record
is first stored) and verify time (verification.py, Phase 2 later) - a
re-hash of the stored fields must reproduce the original hash unless the
data was tampered with.
"""

from __future__ import annotations

import hashlib

_FIELD_SEPARATOR = "|"


def generate_hash(device_id: str, co2: float, sensor_timestamp: str) -> str:
    # co2 is coerced to float and given a fixed str() representation so that
    # e.g. the JSON values 700 (int) and 700.0 (float) - which are numerically
    # identical but arrive as different Python types depending on whether the
    # sender's JSON literal had a decimal point - always hash identically.
    canonical_string = _FIELD_SEPARATOR.join([device_id, str(float(co2)), sensor_timestamp])
    return hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()
