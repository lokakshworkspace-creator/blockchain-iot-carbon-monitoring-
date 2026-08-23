"""Tests for Gateway/events.py's structured event schema."""

from datetime import datetime

from events import Event, EventType, Severity, build_event


def test_build_event_produces_expected_dict_shape():
    event = build_event(
        EventType.THRESHOLD_CRITICAL,
        message="CO2 exceeded critical threshold",
        severity=Severity.CRITICAL,
        device_id="esp32-01",
    )

    assert isinstance(event, Event)
    as_dict = event.to_dict()

    assert as_dict == {
        "event_type": "THRESHOLD_CRITICAL",
        "device_id": "esp32-01",
        "timestamp": event.timestamp,
        "message": "CO2 exceeded critical threshold",
        "severity": "CRITICAL",
    }
    # timestamp must be a real, parseable ISO 8601 datetime.
    datetime.fromisoformat(as_dict["timestamp"])


def test_build_event_device_id_defaults_to_none():
    event = build_event(EventType.TEST_MESSAGE, message="hello", severity=Severity.INFO)
    assert event.device_id is None
    assert event.to_dict()["device_id"] is None


def test_pipeline_b_event_types_are_defined():
    # Locks in the Step 3 (Phase 2) additions so the System Monitor feed has
    # full coverage once database.py/blockchain.py/verification.py emit them.
    expected = {
        "HASH_GENERATED",
        "DATABASE_STORED",
        "BLOCKCHAIN_SUBMITTED",
        "BLOCKCHAIN_CONFIRMED",
        "BLOCKCHAIN_FAILED",
        "VERIFICATION_STARTED",
        "VERIFICATION_SUCCESS",
        "VERIFICATION_FAILED",
        "TAMPERING_DETECTED",
    }
    assert expected.issubset({member.value for member in EventType})
