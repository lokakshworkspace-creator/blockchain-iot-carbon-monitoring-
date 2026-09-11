"""
Tests for Gateway/app.py's Phase 6 notification step - the small piece
spawned right after Pipeline A's existing WebSocket broadcast, not
inside threshold.py itself. Covers exactly the decisions confirmed
before this was built: only THRESHOLD_WARNING/THRESHOLD_CRITICAL ever
produce a notification (never THRESHOLD_RESOLVED), an unregistered
device's event is skipped entirely (never written with a guessed or
null region), the severity mapping is direct (WARNING->"warning",
CRITICAL->"critical"), and delivered_realtime only ends up true when a
live push actually reached a socket.

Same style as test_app_pipeline_b.py: monkeypatched stand-ins for
app.py's module-level dependencies, no real MongoDB or WebSocket needed
- these are unit tests of app.py's own logic, not integration tests of
database.py/notification_rooms.py (those get exercised live in the
manual end-to-end verification instead, the same way Pipeline B's real
Mongo/blockchain calls are).
"""

import asyncio

import app
from events import EventType, Severity, build_event


class _FakeRooms:
    """Stand-in for notification_rooms.rooms - lets a test control
    whether send_to_region() claims a socket received the push."""

    def __init__(self, delivered: bool) -> None:
        self.delivered = delivered
        self.sent_to: list[tuple[str, dict]] = []

    async def send_to_region(self, region_id: str, message: dict) -> bool:
        self.sent_to.append((region_id, message))
        return self.delivered


class _RecordingCreateNotification:
    """Stand-in for database.create_notification - records the call and
    returns an API-shaped dict, like the real function does."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def __call__(self, region_id, factory_id, device_id, co2_value, severity, message) -> dict:
        self.calls.append(
            {
                "region_id": region_id,
                "factory_id": factory_id,
                "device_id": device_id,
                "co2_value": co2_value,
                "severity": severity,
                "message": message,
            }
        )
        return {
            "id": "fake-notification-id",
            "region_id": region_id,
            "factory_id": factory_id,
            "device_id": device_id,
            "co2_value": co2_value,
            "severity": severity,
            "message": message,
            "created_at": "2026-08-23T00:00:00+00:00",
            "delivered_realtime": False,
            "seen_at": None,
            "acknowledged": False,
        }


def _warning_event(device_id: str = "esp32-01") -> object:
    return build_event(
        EventType.THRESHOLD_WARNING, message=f"{device_id} CO2 reading 1200.0 ppm is WARNING",
        severity=Severity.WARNING, device_id=device_id,
    )


def _critical_event(device_id: str = "esp32-01") -> object:
    return build_event(
        EventType.THRESHOLD_CRITICAL, message=f"{device_id} CO2 reading 2500.0 ppm is CRITICAL",
        severity=Severity.CRITICAL, device_id=device_id,
    )


def _resolved_event(device_id: str = "esp32-01") -> object:
    return build_event(
        EventType.THRESHOLD_RESOLVED, message=f"{device_id} CO2 back to normal", severity=Severity.INFO,
        device_id=device_id,
    )


def test_unregistered_device_never_creates_a_notification(monkeypatch):
    async def _unresolved(device_id):
        return None

    create = _RecordingCreateNotification()
    monkeypatch.setattr(app, "get_factory_and_region_for_device", _unresolved)
    monkeypatch.setattr(app, "create_notification", create)
    monkeypatch.setattr(app, "notification_rooms", _FakeRooms(delivered=False))

    asyncio.run(app._process_notification(_warning_event(), 1200.0))

    assert create.calls == []  # never written with a guessed/null region


def test_warning_event_maps_to_warning_severity(monkeypatch):
    async def _resolved(device_id):
        return ("factory-1", "region-1")

    create = _RecordingCreateNotification()
    monkeypatch.setattr(app, "get_factory_and_region_for_device", _resolved)
    monkeypatch.setattr(app, "create_notification", create)
    monkeypatch.setattr(app, "notification_rooms", _FakeRooms(delivered=False))
    monkeypatch.setattr(app, "mark_notification_delivered", lambda notification_id: asyncio.sleep(0))

    asyncio.run(app._process_notification(_warning_event(), 1200.0))

    assert len(create.calls) == 1
    call = create.calls[0]
    assert call["severity"] == "warning"
    assert call["region_id"] == "region-1"
    assert call["factory_id"] == "factory-1"
    assert call["co2_value"] == 1200.0


def test_critical_event_maps_to_critical_severity(monkeypatch):
    async def _resolved(device_id):
        return ("factory-1", "region-1")

    create = _RecordingCreateNotification()
    monkeypatch.setattr(app, "get_factory_and_region_for_device", _resolved)
    monkeypatch.setattr(app, "create_notification", create)
    monkeypatch.setattr(app, "notification_rooms", _FakeRooms(delivered=False))
    monkeypatch.setattr(app, "mark_notification_delivered", lambda notification_id: asyncio.sleep(0))

    asyncio.run(app._process_notification(_critical_event(), 2500.0))

    assert create.calls[0]["severity"] == "critical"


def test_delivered_realtime_is_marked_when_a_socket_receives_it(monkeypatch):
    async def _resolved(device_id):
        return ("factory-1", "region-1")

    marked: list[str] = []

    async def _mark_delivered(notification_id):
        marked.append(notification_id)

    monkeypatch.setattr(app, "get_factory_and_region_for_device", _resolved)
    monkeypatch.setattr(app, "create_notification", _RecordingCreateNotification())
    monkeypatch.setattr(app, "notification_rooms", _FakeRooms(delivered=True))
    monkeypatch.setattr(app, "mark_notification_delivered", _mark_delivered)

    asyncio.run(app._process_notification(_warning_event(), 1200.0))

    assert marked == ["fake-notification-id"]


def test_delivered_realtime_is_not_marked_when_nothing_is_connected(monkeypatch):
    async def _resolved(device_id):
        return ("factory-1", "region-1")

    marked: list[str] = []

    async def _mark_delivered(notification_id):
        marked.append(notification_id)

    monkeypatch.setattr(app, "get_factory_and_region_for_device", _resolved)
    monkeypatch.setattr(app, "create_notification", _RecordingCreateNotification())
    monkeypatch.setattr(app, "notification_rooms", _FakeRooms(delivered=False))
    monkeypatch.setattr(app, "mark_notification_delivered", _mark_delivered)

    asyncio.run(app._process_notification(_warning_event(), 1200.0))

    assert marked == []  # left false, per the spec - never falsely claimed as delivered


def test_resolved_event_never_spawns_a_notification_task(monkeypatch):
    """_spawn_notification() (not _process_notification() directly) is
    what Pipeline A actually calls - this pins down the
    _NOTIFIABLE_EVENT_TYPES filter that keeps THRESHOLD_RESOLVED out
    before a task is even created."""
    called_with: list[object] = []

    async def _fake_process(event, co2):
        called_with.append(event)

    monkeypatch.setattr(app, "_process_notification", _fake_process)

    async def _run():
        app._spawn_notification(_resolved_event(), 700.0)
        app._spawn_notification(_warning_event(), 1200.0)
        await asyncio.sleep(0)  # let any spawned tasks actually run

    asyncio.run(_run())

    assert len(called_with) == 1
    assert called_with[0].event_type == EventType.THRESHOLD_WARNING
