"""
Structured event objects broadcast to dashboard clients over
websocket_manager. This module only defines the shared shape every event
takes on the wire; threshold.py, device_status.py, and (once built)
database.py/blockchain.py/verification.py decide *when* to build one.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime, timezone


class EventType(str, enum.Enum):
    DEVICE_ONLINE = "DEVICE_ONLINE"
    DEVICE_OFFLINE = "DEVICE_OFFLINE"
    THRESHOLD_WARNING = "THRESHOLD_WARNING"
    THRESHOLD_CRITICAL = "THRESHOLD_CRITICAL"
    THRESHOLD_RESOLVED = "THRESHOLD_RESOLVED"
    TEST_MESSAGE = "TEST_MESSAGE"

    # Pipeline B (hash -> MongoDB -> blockchain), for the System Monitor feed.
    HASH_GENERATED = "HASH_GENERATED"
    DATABASE_STORED = "DATABASE_STORED"
    DATABASE_ERROR = "DATABASE_ERROR"
    BLOCKCHAIN_SUBMITTED = "BLOCKCHAIN_SUBMITTED"
    BLOCKCHAIN_CONFIRMED = "BLOCKCHAIN_CONFIRMED"
    BLOCKCHAIN_FAILED = "BLOCKCHAIN_FAILED"
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_SUCCESS = "VERIFICATION_SUCCESS"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    TAMPERING_DETECTED = "TAMPERING_DETECTED"


class Severity(str, enum.Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class Event:
    event_type: EventType
    device_id: str | None
    timestamp: str
    message: str
    severity: Severity

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type.value,
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "message": self.message,
            "severity": self.severity.value,
        }


def build_event(
    event_type: EventType,
    message: str,
    severity: Severity,
    device_id: str | None = None,
) -> Event:
    return Event(
        event_type=event_type,
        device_id=device_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        message=message,
        severity=severity,
    )
