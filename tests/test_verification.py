"""
Tests for Gateway/verification.py's tamper-detection comparison logic,
using fake stand-ins for database.py/blockchain.py (no real Mongo/Sepolia
needed), matching the established fake-object testing style. Covers the
Verified/Tampered/NotAnchored/NotFound paths and, specifically, that a
0x-prefix formatting difference alone never produces a false Tampered
result - the exact class of bug hit in blockchain.py's tx_hash handling
last session.
"""

import asyncio

import verification
from events import EventType
from hashing import generate_hash

DEVICE_ID = "esp32-01"
CO2 = 500.0
SENSOR_TIMESTAMP = "2026-08-23T00:00:00+00:00"
CORRECT_HASH = generate_hash(DEVICE_ID, CO2, SENSOR_TIMESTAMP)


class _BroadcastRecorder:
    def __init__(self) -> None:
        self.broadcast_events: list[dict] = []

    async def broadcast(self, message: dict) -> None:
        self.broadcast_events.append(message)


class _FakeBlockchainClient:
    def __init__(self, onchain_hash) -> None:
        self._onchain_hash = onchain_hash
        self.get_hash_calls: list[int] = []

    async def get_hash(self, record_id: int) -> str:
        self.get_hash_calls.append(record_id)
        return self._onchain_hash


def _make_record(**overrides) -> dict:
    record = {
        "device_id": DEVICE_ID,
        "co2": CO2,
        "sensor_timestamp": SENSOR_TIMESTAMP,
        "hash": CORRECT_HASH,
        "blockchain_record_id": 0,  # a real anchored record can legitimately be id 0
    }
    record.update(overrides)
    return record


def _install_fakes(monkeypatch, record, onchain_hash=None, update_calls=None):
    recorder = _BroadcastRecorder()
    monkeypatch.setattr(verification, "manager", recorder)

    async def _fake_get_record(record_id):
        return record

    monkeypatch.setattr(verification, "get_sensor_record", _fake_get_record)

    async def _fake_update_status(record_id, status):
        if update_calls is not None:
            update_calls.append((record_id, status))

    monkeypatch.setattr(verification, "update_verification_status", _fake_update_status)

    fake_client = _FakeBlockchainClient(onchain_hash)
    monkeypatch.setattr(verification, "blockchain_client", fake_client)

    return recorder, fake_client


def test_verify_record_reports_verified_when_hashes_match(monkeypatch):
    update_calls: list[tuple] = []
    recorder, _ = _install_fakes(monkeypatch, _make_record(), onchain_hash=CORRECT_HASH, update_calls=update_calls)

    result = asyncio.run(verification.verify_record("rec-1"))

    assert result["status"] == "Verified"
    assert result["stored_hash"] == CORRECT_HASH
    assert result["onchain_hash"] == CORRECT_HASH
    assert result["recomputed_hash"] == CORRECT_HASH
    assert update_calls == [("rec-1", "Verified")]

    event_types = [e["event_type"] for e in recorder.broadcast_events]
    assert event_types == [EventType.VERIFICATION_STARTED.value, EventType.VERIFICATION_SUCCESS.value]


def test_verify_record_reports_tampered_when_co2_was_edited_directly(monkeypatch):
    # Simulates the project's core demo scenario: co2 edited directly in
    # MongoDB, "hash" field left stale/untouched.
    tampered_record = _make_record(co2=999.0)
    update_calls: list[tuple] = []
    recorder, _ = _install_fakes(
        monkeypatch, tampered_record, onchain_hash=CORRECT_HASH, update_calls=update_calls
    )

    result = asyncio.run(verification.verify_record("rec-1"))

    assert result["status"] == "Tampered"
    assert result["stored_hash"] == CORRECT_HASH  # the stale hash field, untouched by the tamper
    assert result["onchain_hash"] == CORRECT_HASH
    assert result["recomputed_hash"] != CORRECT_HASH  # recomputed from the now-tampered co2
    assert update_calls == [("rec-1", "Tampered")]

    event_types = [e["event_type"] for e in recorder.broadcast_events]
    assert event_types == [EventType.VERIFICATION_STARTED.value, EventType.TAMPERING_DETECTED.value]

    tampering_event = recorder.broadcast_events[-1]
    assert tampering_event["severity"] == "CRITICAL"
    assert result["recomputed_hash"] in tampering_event["message"]
    assert result["onchain_hash"] in tampering_event["message"]


def test_verify_record_normalizes_0x_prefix_before_comparing(monkeypatch):
    # Same underlying digest, but the on-chain side carries a 0x prefix
    # (and different case) while hashing.generate_hash()'s plain hexdigest
    # never does - must be reported Verified, not a false Tampered.
    onchain_hash_with_prefix = "0x" + CORRECT_HASH.upper()
    recorder, fake_client = _install_fakes(monkeypatch, _make_record(), onchain_hash=onchain_hash_with_prefix)

    result = asyncio.run(verification.verify_record("rec-1"))

    assert result["status"] == "Verified"
    event_types = [e["event_type"] for e in recorder.broadcast_events]
    assert EventType.TAMPERING_DETECTED.value not in event_types
    assert event_types == [EventType.VERIFICATION_STARTED.value, EventType.VERIFICATION_SUCCESS.value]


def test_verify_record_not_yet_anchored_skips_the_compare(monkeypatch):
    record = _make_record(blockchain_record_id=None)
    recorder, fake_client = _install_fakes(monkeypatch, record, onchain_hash=CORRECT_HASH)

    result = asyncio.run(verification.verify_record("rec-1"))

    assert result["status"] == "NotAnchored"
    assert result["onchain_hash"] is None
    assert result["recomputed_hash"] is None
    assert fake_client.get_hash_calls == []  # the on-chain compare was never attempted

    event_types = [e["event_type"] for e in recorder.broadcast_events]
    assert event_types == [EventType.VERIFICATION_STARTED.value, EventType.VERIFICATION_FAILED.value]


def test_verify_record_reports_not_found_for_a_missing_record(monkeypatch):
    recorder = _BroadcastRecorder()
    monkeypatch.setattr(verification, "manager", recorder)

    async def _fake_get_record(record_id):
        return None

    monkeypatch.setattr(verification, "get_sensor_record", _fake_get_record)

    result = asyncio.run(verification.verify_record("missing-id"))

    assert result["status"] == "NotFound"
    event_types = [e["event_type"] for e in recorder.broadcast_events]
    assert event_types == [EventType.VERIFICATION_STARTED.value, EventType.VERIFICATION_FAILED.value]
