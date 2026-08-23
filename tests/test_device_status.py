"""
Unit tests for Gateway/device_status.py's per-device online/offline state
machine. A fake, manually-advanced clock is injected instead of using real
sleep()/datetime.now() calls, so timeout behavior is tested instantly and
deterministically.
"""

import dataclasses
from datetime import datetime, timedelta, timezone

import pytest

import config
import device_status
from device_status import DeviceStatusTracker
from events import EventType, Severity

DEVICE_TIMEOUT_SECONDS = 30


class FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)


@pytest.fixture(autouse=True)
def fixed_timeout(monkeypatch):
    test_settings = dataclasses.replace(config.settings, device_timeout_seconds=DEVICE_TIMEOUT_SECONDS)
    monkeypatch.setattr(device_status, "settings", test_settings)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(datetime(2026, 1, 1, tzinfo=timezone.utc))


@pytest.fixture
def tracker(clock: FakeClock) -> DeviceStatusTracker:
    return DeviceStatusTracker(clock=clock)


def test_first_message_from_new_device_emits_device_online(tracker):
    event = tracker.record_message("esp32-01")
    assert event is not None
    assert event.event_type is EventType.DEVICE_ONLINE
    assert event.severity is Severity.INFO
    assert event.device_id == "esp32-01"


def test_second_message_while_already_online_emits_nothing(tracker):
    tracker.record_message("esp32-01")
    second = tracker.record_message("esp32-01")
    assert second is None


def test_online_stays_online_when_checked_before_timeout(tracker, clock):
    tracker.record_message("esp32-01")
    clock.advance(DEVICE_TIMEOUT_SECONDS - 1)
    assert tracker.check_timeouts() == []


def test_device_goes_offline_after_timeout_elapses(tracker, clock):
    tracker.record_message("esp32-01")
    clock.advance(DEVICE_TIMEOUT_SECONDS + 1)

    events = tracker.check_timeouts()

    assert len(events) == 1
    assert events[0].event_type is EventType.DEVICE_OFFLINE
    assert events[0].severity is Severity.WARNING
    assert events[0].device_id == "esp32-01"


def test_offline_device_is_not_reported_again_on_later_checks(tracker, clock):
    tracker.record_message("esp32-01")
    clock.advance(DEVICE_TIMEOUT_SECONDS + 1)
    tracker.check_timeouts()  # first detection

    clock.advance(60)
    assert tracker.check_timeouts() == []


def test_new_message_after_offline_emits_device_online_again(tracker, clock):
    tracker.record_message("esp32-01")
    clock.advance(DEVICE_TIMEOUT_SECONDS + 1)
    tracker.check_timeouts()

    event = tracker.record_message("esp32-01")

    assert event is not None
    assert event.event_type is EventType.DEVICE_ONLINE


def test_snapshot_reflects_current_state(tracker, clock):
    tracker.record_message("esp32-01")
    seen_at = clock().isoformat()  # last_seen is stamped at record_message time, not later
    clock.advance(DEVICE_TIMEOUT_SECONDS + 1)
    tracker.check_timeouts()

    snapshot = tracker.snapshot()

    assert snapshot == [{"device_id": "esp32-01", "online": False, "last_seen": seen_at}]


def test_devices_have_independent_state(tracker, clock):
    tracker.record_message("esp32-01")
    clock.advance(DEVICE_TIMEOUT_SECONDS + 1)
    tracker.record_message("esp32-02")  # freshly seen, must not be affected by esp32-01's age

    events = tracker.check_timeouts()

    assert len(events) == 1
    assert events[0].device_id == "esp32-01"
