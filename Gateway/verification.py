"""
Phase 2's last piece: proves (or disproves) that a MongoDB sensor record's
data hasn't been altered since it was hashed and anchored on Sepolia.

The comparison that matters is recomputed_hash (hashed fresh from whatever
device_id/co2/sensor_timestamp are CURRENTLY in the MongoDB document)
against onchain_hash (the immutable hash CarbonMonitor.sol has recorded).
If someone edits co2 directly in the database, recomputed_hash changes but
onchain_hash can't - that mismatch is what "tampering" means here. Naive
string equality between the two is unsafe: blockchain.py's tx_hash briefly
had a real 0x-prefix inconsistency, and hashing.generate_hash() vs a
contract getHash() call are not guaranteed to agree on 0x-prefix
convention either. Every comparison here goes through _normalize_hash()
first so a formatting difference alone can never produce a false
"Tampered" verdict.

No on-chain verifyHash() per CLAUDE.md - all of this comparison logic
stays in Python.
"""

from __future__ import annotations

import logging

from blockchain import client as blockchain_client
from database import get_sensor_record, update_verification_status
from events import EventType, Severity, build_event
from hashing import generate_hash
from websocket_manager import manager

logger = logging.getLogger(__name__)


def _normalize_hash(value: str) -> str:
    value = value.strip()
    if value.startswith(("0x", "0X")):
        value = value[2:]
    return value.lower()


async def verify_record(record_id: str) -> dict:
    await manager.broadcast(
        build_event(
            EventType.VERIFICATION_STARTED,
            message=f"Verification started for record {record_id}",
            severity=Severity.INFO,
        ).to_dict()
    )

    try:
        record = await get_sensor_record(record_id)
    except Exception as exc:
        logger.exception("Verification could not fetch record %s", record_id)
        await manager.broadcast(
            build_event(
                EventType.VERIFICATION_FAILED,
                message=f"Verification for record {record_id} failed: could not read from MongoDB ({exc})",
                severity=Severity.CRITICAL,
            ).to_dict()
        )
        return {"status": "Error", "stored_hash": None, "onchain_hash": None, "recomputed_hash": None}

    if record is None:
        await manager.broadcast(
            build_event(
                EventType.VERIFICATION_FAILED,
                message=f"Verification for record {record_id} failed: no such record",
                severity=Severity.WARNING,
            ).to_dict()
        )
        return {"status": "NotFound", "stored_hash": None, "onchain_hash": None, "recomputed_hash": None}

    device_id = record.get("device_id")
    stored_hash = record.get("hash")
    blockchain_record_id = record.get("blockchain_record_id")

    if blockchain_record_id is None:
        await manager.broadcast(
            build_event(
                EventType.VERIFICATION_FAILED,
                message=f"Record {record_id} has not been anchored on-chain yet",
                severity=Severity.WARNING,
                device_id=device_id,
            ).to_dict()
        )
        return {"status": "NotAnchored", "stored_hash": stored_hash, "onchain_hash": None, "recomputed_hash": None}

    try:
        recomputed_hash = generate_hash(record["device_id"], record["co2"], record["sensor_timestamp"])
        onchain_hash = await blockchain_client.get_hash(blockchain_record_id)
    except Exception as exc:
        logger.exception("Verification could not complete the on-chain comparison for record %s", record_id)
        await manager.broadcast(
            build_event(
                EventType.VERIFICATION_FAILED,
                message=f"Verification for record {record_id} failed: {exc}",
                severity=Severity.CRITICAL,
                device_id=device_id,
            ).to_dict()
        )
        return {"status": "Error", "stored_hash": stored_hash, "onchain_hash": None, "recomputed_hash": None}

    is_match = _normalize_hash(recomputed_hash) == _normalize_hash(onchain_hash)
    status = "Verified" if is_match else "Tampered"

    await update_verification_status(record_id, status)

    if is_match:
        await manager.broadcast(
            build_event(
                EventType.VERIFICATION_SUCCESS,
                message=f"Record {record_id} verified: data matches the on-chain hash",
                severity=Severity.INFO,
                device_id=device_id,
            ).to_dict()
        )
    else:
        # Distinct from VERIFICATION_FAILED: the check itself worked fine -
        # it found that the data doesn't match what was anchored.
        await manager.broadcast(
            build_event(
                EventType.TAMPERING_DETECTED,
                message=(
                    f"Record {record_id} TAMPERING DETECTED: recomputed hash {recomputed_hash} "
                    f"does not match on-chain hash {onchain_hash} (stored hash: {stored_hash})"
                ),
                severity=Severity.CRITICAL,
                device_id=device_id,
            ).to_dict()
        )

    return {
        "status": status,
        "stored_hash": stored_hash,
        "onchain_hash": onchain_hash,
        "recomputed_hash": recomputed_hash,
    }
