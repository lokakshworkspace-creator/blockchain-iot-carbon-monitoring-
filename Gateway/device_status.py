"""
Tracks per-device last-seen timestamps and flags a device OFFLINE once
DEVICE_TIMEOUT_SECONDS has passed with no messages. Mirrors threshold.py's
shape: a pure per-device state dict that returns Events for the caller to
broadcast, with no WebSocket/asyncio dependencies of its own so it stays
easy to unit test with a fake clock. app.py owns the periodic timeout check
and does the actual broadcasting, the same way it does for threshold.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from config import settings
from events import Event, EventType, Severity, build_event

logger = logging.getLogger(__name__)

ClockFn = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class _DeviceState:
    last_seen: datetime
    online: bool = True


class DeviceStatusTracker:
    def __init__(self, clock: ClockFn = _utcnow) -> None:
        self._clock = clock
        self._states: dict[str, _DeviceState] = {}

    def record_message(self, device_id: str) -> Event | None:
        """Call once for every valid message that reaches the consumer.
        Returns a DEVICE_ONLINE event if this device was offline or unseen
        before now, else None (already online - nothing changed)."""
        now = self._clock()
        state = self._states.get(device_id)

        if state is None:
            self._states[device_id] = _DeviceState(last_seen=now, online=True)
            return build_event(
                EventType.DEVICE_ONLINE,
                message=f"{device_id} came online",
                severity=Severity.INFO,
                device_id=device_id,
            )

        was_offline = not state.online
        state.last_seen = now
        state.online = True

        if was_offline:
            return build_event(
                EventType.DEVICE_ONLINE,
                message=f"{device_id} came back online",
                severity=Severity.INFO,
                device_id=device_id,
            )
        return None

    def check_timeouts(self) -> list[Event]:
        """Call periodically. Returns one DEVICE_OFFLINE event for every
        device that just crossed DEVICE_TIMEOUT_SECONDS of silence (a
        device already marked offline is not re-reported on later calls)."""
        now = self._clock()
        timeout = timedelta(seconds=settings.device_timeout_seconds)
        events: list[Event] = []

        for device_id, state in self._states.items():
            if state.online and (now - state.last_seen) > timeout:
                state.online = False
                events.append(
                    build_event(
                        EventType.DEVICE_OFFLINE,
                        message=f"{device_id} has not reported in over {settings.device_timeout_seconds}s",
                        severity=Severity.WARNING,
                        device_id=device_id,
                    )
                )
        return events

    def snapshot(self) -> list[dict]:
        """Current status of every device seen so far, for GET /devices/status."""
        return [
            {
                "device_id": device_id,
                "online": state.online,
                "last_seen": state.last_seen.isoformat(),
            }
            for device_id, state in self._states.items()
        ]


tracker = DeviceStatusTracker()
