"""
Tests for Gateway/app.py's Pipeline B error handling. A failure inside
_process_pipeline_b - either the hash/DB stage or the blockchain stage -
must be caught, logged, and broadcast as a DATABASE_ERROR/BLOCKCHAIN_FAILED
event - never left to propagate and silently kill the background task it
runs in. The DB and blockchain stages have independent try/except blocks,
so a blockchain failure must not retroactively affect the DATABASE_STORED
event that already fired.
"""

import asyncio

import app
from events import EventType


class _FakeBlockchainClient:
    """Stand-in for blockchain.client - avoids touching the real (possibly
    unstarted/unconfigured) singleton in these tests."""

    def __init__(self, result: dict | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    async def store_hash(self, hash_hex: str) -> dict:
        if self._error is not None:
            raise self._error
        return self._result


class _BroadcastRecorder:
    """Stand-in for websocket_manager.manager - records every event dict
    passed to broadcast() instead of actually sending anything."""

    def __init__(self) -> None:
        self.broadcast_events: list[dict] = []

    async def broadcast(self, message: dict) -> None:
        self.broadcast_events.append(message)


def _sample_message() -> dict:
    return {
        "device_id": "esp32-01",
        "co2": 500.0,
        "sensor_timestamp": "2026-08-23T00:00:00+00:00",
        "gateway_received_timestamp": "2026-08-23T00:00:00.100000+00:00",
    }


def test_pipeline_b_survives_insert_failure_and_broadcasts_database_error(monkeypatch, caplog):
    recorder = _BroadcastRecorder()
    monkeypatch.setattr(app, "manager", recorder)

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated MongoDB outage")

    monkeypatch.setattr(app, "insert_sensor_record", _boom)

    with caplog.at_level("ERROR"):
        asyncio.run(app._process_pipeline_b(_sample_message()))  # must not raise

    event_types = [event["event_type"] for event in recorder.broadcast_events]
    assert event_types == [EventType.HASH_GENERATED.value, EventType.DATABASE_ERROR.value]

    error_event = recorder.broadcast_events[1]
    assert error_event["severity"] == "CRITICAL"
    assert error_event["device_id"] == "esp32-01"
    assert "simulated MongoDB outage" in error_event["message"]
    assert "Pipeline B (hash/DB) failed" in caplog.text
    assert "simulated MongoDB outage" in caplog.text


def test_pipeline_b_happy_path_reaches_blockchain_confirmed(monkeypatch):
    recorder = _BroadcastRecorder()
    monkeypatch.setattr(app, "manager", recorder)

    async def _fake_insert(*args, **kwargs):
        return "fake-record-id"

    monkeypatch.setattr(app, "insert_sensor_record", _fake_insert)

    async def _fake_update_blockchain_info(*args, **kwargs):
        return None

    monkeypatch.setattr(app, "update_blockchain_info", _fake_update_blockchain_info)
    monkeypatch.setattr(
        app,
        "blockchain_client",
        _FakeBlockchainClient(result={"tx_hash": "0xabc123", "record_id": 7, "block_number": 999}),
    )

    asyncio.run(app._process_pipeline_b(_sample_message()))

    event_types = [event["event_type"] for event in recorder.broadcast_events]
    assert event_types == [
        EventType.HASH_GENERATED.value,
        EventType.DATABASE_STORED.value,
        EventType.BLOCKCHAIN_SUBMITTED.value,
        EventType.BLOCKCHAIN_CONFIRMED.value,
    ]
    confirmed_event = recorder.broadcast_events[-1]
    assert "0xabc123" in confirmed_event["message"]
    assert "7" in confirmed_event["message"]


def test_pipeline_b_blockchain_failure_does_not_undo_database_stored(monkeypatch, caplog):
    recorder = _BroadcastRecorder()
    monkeypatch.setattr(app, "manager", recorder)

    async def _fake_insert(*args, **kwargs):
        return "fake-record-id"

    monkeypatch.setattr(app, "insert_sensor_record", _fake_insert)
    monkeypatch.setattr(
        app, "blockchain_client", _FakeBlockchainClient(error=RuntimeError("simulated Sepolia RPC outage"))
    )

    with caplog.at_level("ERROR"):
        asyncio.run(app._process_pipeline_b(_sample_message()))  # must not raise

    event_types = [event["event_type"] for event in recorder.broadcast_events]
    assert event_types == [
        EventType.HASH_GENERATED.value,
        EventType.DATABASE_STORED.value,  # still fired - the DB write genuinely succeeded
        EventType.BLOCKCHAIN_SUBMITTED.value,
        EventType.BLOCKCHAIN_FAILED.value,
    ]
    failed_event = recorder.broadcast_events[-1]
    assert failed_event["severity"] == "CRITICAL"
    assert "simulated Sepolia RPC outage" in failed_event["message"]
    assert "simulated Sepolia RPC outage" in caplog.text
