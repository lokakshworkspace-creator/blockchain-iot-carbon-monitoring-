"""
Tests for Gateway/app.py's Pipeline B error handling. A failure inside
_process_pipeline_b (most realistically a MongoDB write failure) must be
caught, logged, and broadcast as a DATABASE_ERROR event - never left to
propagate and silently kill the background task it runs in.
"""

import asyncio

import app
from events import EventType


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
    assert "Pipeline B failed" in caplog.text
    assert "simulated MongoDB outage" in caplog.text


def test_pipeline_b_happy_path_does_not_emit_database_error(monkeypatch):
    recorder = _BroadcastRecorder()
    monkeypatch.setattr(app, "manager", recorder)

    async def _fake_insert(*args, **kwargs):
        return "fake-record-id"

    monkeypatch.setattr(app, "insert_sensor_record", _fake_insert)

    asyncio.run(app._process_pipeline_b(_sample_message()))

    event_types = [event["event_type"] for event in recorder.broadcast_events]
    assert event_types == [EventType.HASH_GENERATED.value, EventType.DATABASE_STORED.value]
