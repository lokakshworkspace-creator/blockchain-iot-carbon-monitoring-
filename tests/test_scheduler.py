"""
Tests for Gateway/scheduler.py's periodic tamper-check cycle, using the
same fake-object style as verification.py's and app.py's tests.

scheduler.run_verification_cycle() only decides WHEN and WHICH records to
check - the actual hash comparison lives entirely in
verification.verify_record(), which these tests confirm the scheduler
calls directly rather than reimplementing. Patching verification.py's own
module-level manager/get_sensor_record/update_verification_status/
blockchain_client (not scheduler.py's) is deliberate and mirrors
test_verification.py exactly: verify_record()'s body looks those names up
in verification.py's own globals at call time, regardless of which module
holds a reference to the function object, so that's the correct patch
target for a real (not faked) verify_record call.
"""

import asyncio

import scheduler
from events import EventType
from hashing import generate_hash

DEVICE_ID = "esp32-01"
CO2 = 650.0
SENSOR_TIMESTAMP = "2026-08-24T00:00:00+00:00"
CORRECT_HASH = generate_hash(DEVICE_ID, CO2, SENSOR_TIMESTAMP)


class _BroadcastRecorder:
    def __init__(self) -> None:
        self.broadcast_events: list[dict] = []

    async def broadcast(self, message: dict) -> None:
        self.broadcast_events.append(message)


def _make_record(**overrides) -> dict:
    record = {
        "device_id": DEVICE_ID,
        "co2": CO2,
        "sensor_timestamp": SENSOR_TIMESTAMP,
        "hash": CORRECT_HASH,
        "blockchain_record_id": 0,
    }
    record.update(overrides)
    return record


def _install_real_verify_record_fakes(monkeypatch, records_by_id, onchain_hashes, update_calls=None):
    """Wires up verification.py's own dependencies so scheduler.py's real,
    unmodified verify_record() import runs its genuine comparison logic
    end to end - nothing about the comparison itself is faked, only its
    I/O (Mongo, Sepolia, the WebSocket)."""
    recorder = _BroadcastRecorder()
    monkeypatch.setattr("verification.manager", recorder)

    async def _fake_get_record(record_id):
        return records_by_id.get(record_id)

    monkeypatch.setattr("verification.get_sensor_record", _fake_get_record)

    async def _fake_update_status(record_id, status):
        if update_calls is not None:
            update_calls.append((record_id, status))

    monkeypatch.setattr("verification.update_verification_status", _fake_update_status)

    class _FakeBlockchainClient:
        async def get_hash(self, record_id):
            return onchain_hashes[record_id]

    monkeypatch.setattr("verification.blockchain_client", _FakeBlockchainClient())

    return recorder


def test_cycle_fetches_the_configured_sample_size_of_recent_records(monkeypatch):
    requested_limits = []

    async def _fake_get_recently_anchored(limit):
        requested_limits.append(limit)
        return []

    monkeypatch.setattr(scheduler, "get_recently_anchored_records", _fake_get_recently_anchored)

    asyncio.run(scheduler.run_verification_cycle())

    assert requested_limits == [scheduler.RECHECK_SAMPLE_SIZE]


def test_cycle_calls_verify_record_once_per_sampled_id_and_marks_each_checked(monkeypatch):
    # verify_record itself is swapped out here (rather than run for real)
    # specifically to prove the scheduler's own responsibility in
    # isolation: it must call verify_record with each sampled id and
    # nothing else, and must not branch on or reinterpret the result -
    # that only the mark_auto_verified bookkeeping call happens alongside it.
    sample_ids = ["rec-1", "rec-2", "rec-3"]

    async def _fake_get_recently_anchored(limit):
        return [{"id": rid} for rid in sample_ids]

    monkeypatch.setattr(scheduler, "get_recently_anchored_records", _fake_get_recently_anchored)

    verify_calls: list[str] = []

    async def _fake_verify_record(record_id):
        verify_calls.append(record_id)
        return {"status": "Verified"}  # the return value is deliberately ignored by the scheduler

    monkeypatch.setattr(scheduler, "verify_record", _fake_verify_record)

    mark_calls: list[str] = []

    async def _fake_mark_auto_verified(record_id):
        mark_calls.append(record_id)

    monkeypatch.setattr(scheduler, "mark_auto_verified", _fake_mark_auto_verified)

    asyncio.run(scheduler.run_verification_cycle())

    assert verify_calls == sample_ids
    assert mark_calls == sample_ids


def test_cycle_reports_tampering_detected_through_the_real_verify_record(monkeypatch):
    # This is the end-to-end proof that matters: a scheduled cycle
    # processing a genuinely tampered record broadcasts TAMPERING_DETECTED
    # via verification.py's own real, unmodified logic - the scheduler
    # never reimplements the comparison.
    tampered_record = _make_record(co2=999.0)  # co2 edited directly, hash field left stale

    async def _fake_get_recently_anchored(limit):
        return [{"id": "rec-1"}]

    monkeypatch.setattr(scheduler, "get_recently_anchored_records", _fake_get_recently_anchored)

    async def _fake_mark_auto_verified(record_id):
        pass

    monkeypatch.setattr(scheduler, "mark_auto_verified", _fake_mark_auto_verified)

    recorder = _install_real_verify_record_fakes(
        monkeypatch,
        records_by_id={"rec-1": tampered_record},
        onchain_hashes={0: CORRECT_HASH},
    )

    asyncio.run(scheduler.run_verification_cycle())

    event_types = [e["event_type"] for e in recorder.broadcast_events]
    assert event_types == [EventType.VERIFICATION_STARTED.value, EventType.TAMPERING_DETECTED.value]

    tampering_event = recorder.broadcast_events[-1]
    assert tampering_event["severity"] == "CRITICAL"


def test_cycle_reports_verification_success_through_the_real_verify_record(monkeypatch):
    # The companion happy-path case: an untampered anchored record checked
    # by a scheduled cycle reports Verified, identically to a manual check.
    update_calls: list[tuple] = []

    async def _fake_get_recently_anchored(limit):
        return [{"id": "rec-1"}]

    monkeypatch.setattr(scheduler, "get_recently_anchored_records", _fake_get_recently_anchored)

    marked: list[str] = []

    async def _fake_mark_auto_verified(record_id):
        marked.append(record_id)

    monkeypatch.setattr(scheduler, "mark_auto_verified", _fake_mark_auto_verified)

    recorder = _install_real_verify_record_fakes(
        monkeypatch,
        records_by_id={"rec-1": _make_record()},
        onchain_hashes={0: CORRECT_HASH},
        update_calls=update_calls,
    )

    asyncio.run(scheduler.run_verification_cycle())

    event_types = [e["event_type"] for e in recorder.broadcast_events]
    assert event_types == [EventType.VERIFICATION_STARTED.value, EventType.VERIFICATION_SUCCESS.value]
    assert update_calls == [("rec-1", "Verified")]
    assert marked == ["rec-1"]  # only auto-verified once the check actually completed


def test_cycle_survives_a_failure_on_one_record_and_still_checks_the_rest(monkeypatch):
    sample_ids = ["rec-1", "rec-2", "rec-3"]

    async def _fake_get_recently_anchored(limit):
        return [{"id": rid} for rid in sample_ids]

    monkeypatch.setattr(scheduler, "get_recently_anchored_records", _fake_get_recently_anchored)

    verify_calls: list[str] = []

    async def _fake_verify_record(record_id):
        verify_calls.append(record_id)
        return {"status": "Verified"}

    monkeypatch.setattr(scheduler, "verify_record", _fake_verify_record)

    async def _fake_mark_auto_verified(record_id):
        if record_id == "rec-2":
            raise RuntimeError("simulated Mongo write failure")

    monkeypatch.setattr(scheduler, "mark_auto_verified", _fake_mark_auto_verified)

    asyncio.run(scheduler.run_verification_cycle())  # must not raise

    # rec-2's bookkeeping failure must not have stopped rec-3 from being checked.
    assert verify_calls == sample_ids


def test_cycle_handles_a_failure_fetching_the_sample_without_raising(monkeypatch):
    async def _fake_get_recently_anchored(limit):
        raise RuntimeError("simulated Mongo outage")

    monkeypatch.setattr(scheduler, "get_recently_anchored_records", _fake_get_recently_anchored)

    verify_calls: list[str] = []

    async def _fake_verify_record(record_id):
        verify_calls.append(record_id)
        return {"status": "Verified"}

    monkeypatch.setattr(scheduler, "verify_record", _fake_verify_record)

    asyncio.run(scheduler.run_verification_cycle())  # must not raise

    assert verify_calls == []
