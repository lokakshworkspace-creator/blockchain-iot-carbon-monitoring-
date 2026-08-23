"""
Tests for the SENSOR_READING telemetry event that app.py's MQTT consumer
broadcasts for every valid reading.

The point of this event is that it is *unconditional* - the dashboard's
live chart needs one data point per reading, whereas threshold.py only
emits on state transitions. The risk in adding it was that it might
interfere with threshold.py's cooldown/hysteresis state machine, so the
second test here pins that down explicitly: the engine must end up in
byte-identical state to one fed the same readings with no telemetry
involved at all.

These drive the real _consume_mqtt_messages() loop rather than
reimplementing it, with fresh (monkeypatched) engine/tracker/queue
instances so the module-level singletons aren't shared between tests.
"""

import asyncio

import pytest

import app
from config import settings
from device_status import DeviceStatusTracker
from events import EventType
from threshold import ThresholdEngine


class _BroadcastRecorder:
    def __init__(self) -> None:
        self.broadcast_events: list[dict] = []

    async def broadcast(self, message: dict) -> None:
        self.broadcast_events.append(message)

    def types(self) -> list[str]:
        return [event["event_type"] for event in self.broadcast_events]

    def of_type(self, event_type: EventType) -> list[dict]:
        return [e for e in self.broadcast_events if e["event_type"] == event_type.value]


def _reading(co2: float) -> dict:
    return {
        "device_id": "esp32-01",
        "co2": co2,
        "sensor_timestamp": "2026-08-23T00:00:00+00:00",
        "gateway_received_timestamp": "2026-08-23T00:00:00.100000+00:00",
    }


@pytest.fixture
def isolated_app(monkeypatch):
    """app.py's engine/tracker/queue are module-level singletons; give each
    test its own so ordering between tests can't change the outcome."""
    recorder = _BroadcastRecorder()
    engine = ThresholdEngine()

    monkeypatch.setattr(app, "manager", recorder)
    monkeypatch.setattr(app, "threshold_engine", engine)
    monkeypatch.setattr(app, "device_status_tracker", DeviceStatusTracker())
    # Pipeline B needs MongoDB and Sepolia; neither belongs in a unit test.
    monkeypatch.setattr(app, "_spawn_pipeline_b", lambda message: None)

    return recorder, engine


async def _feed(readings: list[dict]) -> None:
    """Push readings through the real consumer loop and let it drain."""
    queue: asyncio.Queue = asyncio.Queue()
    app.mqtt_queue = queue  # consumer reads the module global

    consumer = asyncio.create_task(app._consume_mqtt_messages())
    for reading in readings:
        await queue.put(reading)

    # The consumer calls task_done() for nothing, so join() isn't usable;
    # yielding until the queue is drained is enough and stays fast.
    while not queue.empty():
        await asyncio.sleep(0)
    await asyncio.sleep(0)  # let the final iteration's awaits complete

    consumer.cancel()
    try:
        await consumer
    except asyncio.CancelledError:
        pass


def test_every_valid_reading_broadcasts_sensor_reading_with_its_co2(isolated_app):
    recorder, _ = isolated_app
    normal = settings.co2_warning_threshold - 100

    asyncio.run(_feed([_reading(normal), _reading(normal + 1), _reading(normal + 2)]))

    readings = recorder.of_type(EventType.SENSOR_READING)
    assert len(readings) == 3  # one per message, unlike transition-only threshold events
    assert [e["data"]["co2"] for e in readings] == [normal, normal + 1, normal + 2]
    assert readings[0]["device_id"] == "esp32-01"
    assert readings[0]["severity"] == "INFO"

    # Emitted before Pipeline A does anything with the message.
    assert recorder.types()[0] == EventType.SENSOR_READING.value


def test_sensor_reading_does_not_disturb_threshold_hysteresis_state(isolated_app):
    recorder, engine = isolated_app

    normal = settings.co2_warning_threshold - 100
    warning = settings.co2_warning_threshold + 50
    critical = settings.co2_critical_threshold + 50

    # A sequence that exercises open -> cooldown -> escalate -> resolve.
    sequence = [warning, warning, warning, critical, normal] + [normal] * settings.co2_hysteresis_readings

    asyncio.run(_feed([_reading(co2) for co2 in sequence]))

    # Telemetry fires for every reading...
    assert len(recorder.of_type(EventType.SENSOR_READING)) == len(sequence)

    # ...while the alert lifecycle still fires only on transitions: the
    # repeated warnings are swallowed by the cooldown exactly as before.
    assert [t for t in recorder.types() if t.startswith("THRESHOLD_")] == [
        EventType.THRESHOLD_WARNING.value,
        EventType.THRESHOLD_CRITICAL.value,
        EventType.THRESHOLD_RESOLVED.value,
    ]

    # The decisive check: an engine fed the same readings with no telemetry
    # in the picture must end in exactly the same state.
    reference = ThresholdEngine()
    for co2 in sequence:
        reference.evaluate("esp32-01", co2)

    assert engine._states == reference._states
