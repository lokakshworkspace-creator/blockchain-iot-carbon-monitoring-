"""
Unit tests for Gateway/threshold.py's per-device state machine: NORMAL/
WARNING/CRITICAL classification, the ACTIVE -> RESOLVED alert lifecycle,
and hysteresis/cooldown. These fix warning/critical/hysteresis at known
values (independent of whatever the developer's local Gateway/.env
happens to contain) by monkeypatching threshold.settings.
"""

import dataclasses

import pytest

import config
import threshold
from events import EventType, Severity
from threshold import ThresholdEngine

WARNING = 1000.0
CRITICAL = 2000.0
HYSTERESIS = 3


@pytest.fixture(autouse=True)
def fixed_thresholds(monkeypatch):
    test_settings = dataclasses.replace(
        config.settings,
        co2_warning_threshold=WARNING,
        co2_critical_threshold=CRITICAL,
        co2_hysteresis_readings=HYSTERESIS,
    )
    monkeypatch.setattr(threshold, "settings", test_settings)


@pytest.fixture
def engine() -> ThresholdEngine:
    return ThresholdEngine()


def test_normal_reading_with_no_active_alert_produces_no_event(engine):
    assert engine.evaluate("esp32-01", 500.0) is None


def test_warning_reading_opens_alert(engine):
    event = engine.evaluate("esp32-01", WARNING + 100)
    assert event is not None
    assert event.event_type is EventType.THRESHOLD_WARNING
    assert event.severity is Severity.WARNING
    assert event.device_id == "esp32-01"


def test_second_consecutive_warning_reading_does_not_refire(engine):
    first = engine.evaluate("esp32-01", WARNING + 100)
    second = engine.evaluate("esp32-01", WARNING + 150)
    assert first is not None
    assert second is None


def test_critical_reading_escalates_an_active_warning_alert(engine):
    engine.evaluate("esp32-01", WARNING + 100)
    escalation = engine.evaluate("esp32-01", CRITICAL + 200)
    assert escalation is not None
    assert escalation.event_type is EventType.THRESHOLD_CRITICAL
    assert escalation.severity is Severity.CRITICAL


def test_second_consecutive_critical_reading_does_not_refire(engine):
    engine.evaluate("esp32-01", WARNING + 100)
    engine.evaluate("esp32-01", CRITICAL + 200)
    repeat = engine.evaluate("esp32-01", CRITICAL + 300)
    assert repeat is None


def test_lower_severity_reading_does_not_deescalate_or_refire(engine):
    engine.evaluate("esp32-01", WARNING + 100)
    engine.evaluate("esp32-01", CRITICAL + 200)
    # A WARNING-range reading while a CRITICAL alert is active: cooldown,
    # not a demotion back to WARNING.
    dip = engine.evaluate("esp32-01", WARNING + 50)
    assert dip is None


def test_resolve_requires_hysteresis_consecutive_normal_readings(engine):
    engine.evaluate("esp32-01", WARNING + 100)  # opens the alert

    # HYSTERESIS - 1 normal readings: must NOT resolve yet.
    for _ in range(HYSTERESIS - 1):
        assert engine.evaluate("esp32-01", 500.0) is None

    # The Nth consecutive normal reading resolves it.
    resolved = engine.evaluate("esp32-01", 500.0)
    assert resolved is not None
    assert resolved.event_type is EventType.THRESHOLD_RESOLVED
    assert resolved.severity is Severity.INFO


def test_non_normal_reading_resets_the_normal_streak(engine):
    engine.evaluate("esp32-01", WARNING + 100)  # opens the alert

    engine.evaluate("esp32-01", 500.0)  # 1 normal
    engine.evaluate("esp32-01", 500.0)  # 2 normal (one short of HYSTERESIS=3)
    engine.evaluate("esp32-01", WARNING + 50)  # non-normal: resets the streak

    # Two more normals only reaches 2 consecutive again, not 3 - must not resolve.
    assert engine.evaluate("esp32-01", 500.0) is None
    assert engine.evaluate("esp32-01", 500.0) is None
    # The third consecutive normal reading (after the reset) resolves it.
    resolved = engine.evaluate("esp32-01", 500.0)
    assert resolved is not None
    assert resolved.event_type is EventType.THRESHOLD_RESOLVED


def test_non_numeric_co2_is_ignored_without_raising(engine, caplog):
    result = engine.evaluate("esp32-01", "not-a-number")  # must not raise
    assert result is None
    assert "not numeric" in caplog.text


def test_devices_have_independent_state(engine):
    warning_a = engine.evaluate("esp32-01", WARNING + 100)
    # A fresh device seeing the same warning-range reading must also open
    # its own alert - state must not be shared across device_ids.
    warning_b = engine.evaluate("esp32-02", WARNING + 100)

    assert warning_a is not None
    assert warning_b is not None
    assert warning_a.device_id == "esp32-01"
    assert warning_b.device_id == "esp32-02"
