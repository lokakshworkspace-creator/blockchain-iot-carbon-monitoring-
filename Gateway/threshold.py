"""
Pipeline A: classifies each incoming CO2 reading as NORMAL/WARNING/CRITICAL
and turns that into an ACTIVE -> RESOLVED alert lifecycle per device, with
hysteresis so alerts don't flap near a threshold boundary. This module only
decides *whether* an event should fire; app.py is responsible for actually
broadcasting whatever Event it gets back over the WebSocket manager.

State machine per device_id:
- A reading at WARNING/CRITICAL that finds no active alert opens one and
  emits THRESHOLD_WARNING/THRESHOLD_CRITICAL.
- While an alert is ACTIVE, a further reading at the same or a lower
  severity is swallowed silently (the cooldown) - only a reading at a
  *higher* severity than the current alert escalates it, re-emitting the
  event at the new severity.
- A reading below CO2_WARNING_THRESHOLD counts toward auto-resolving the
  active alert, but only once CO2_HYSTERESIS_READINGS consecutive normal
  readings have been seen in a row; any non-normal reading in between
  resets that count. On resolve, THRESHOLD_RESOLVED fires and the device
  goes back to a clean NORMAL state with no active alert.
"""

from __future__ import annotations

import enum
import logging
from dataclasses import dataclass, field

from config import settings
from events import Event, EventType, Severity, build_event

logger = logging.getLogger(__name__)


class Level(enum.IntEnum):
    """Ordered so a plain > comparison tells us whether a reading escalates
    an already-active alert."""

    NORMAL = 0
    WARNING = 1
    CRITICAL = 2


def _classify(co2: float) -> Level:
    if co2 >= settings.co2_critical_threshold:
        return Level.CRITICAL
    if co2 >= settings.co2_warning_threshold:
        return Level.WARNING
    return Level.NORMAL


def _threshold_event(device_id: str, level: Level, co2: float) -> Event:
    event_type = EventType.THRESHOLD_CRITICAL if level is Level.CRITICAL else EventType.THRESHOLD_WARNING
    severity = Severity.CRITICAL if level is Level.CRITICAL else Severity.WARNING
    return build_event(
        event_type,
        message=f"{device_id} CO2 reading {co2} ppm is {level.name}",
        severity=severity,
        device_id=device_id,
    )


@dataclass
class _DeviceState:
    alert_active: bool = False
    active_level: Level | None = None
    consecutive_normal_count: int = field(default=0)


class ThresholdEngine:
    def __init__(self) -> None:
        self._states: dict[str, _DeviceState] = {}

    def evaluate(self, device_id: str, co2: object) -> Event | None:
        """Feed one reading into this device's state machine. Returns the
        Event to broadcast, or None if nothing changed (cooldown / no
        active alert / not enough consecutive readings to resolve yet)."""
        try:
            co2_value = float(co2)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            logger.warning("Ignoring reading from %s: co2 value %r is not numeric", device_id, co2)
            return None

        state = self._states.setdefault(device_id, _DeviceState())
        level = _classify(co2_value)

        if level is Level.NORMAL:
            state.consecutive_normal_count += 1
            if state.alert_active and state.consecutive_normal_count >= settings.co2_hysteresis_readings:
                resolved_from = state.active_level
                state.alert_active = False
                state.active_level = None
                state.consecutive_normal_count = 0
                return build_event(
                    EventType.THRESHOLD_RESOLVED,
                    message=f"{device_id} CO2 back to normal ({co2_value} ppm), resolving {resolved_from.name} alert",
                    severity=Severity.INFO,
                    device_id=device_id,
                )
            return None

        # WARNING or CRITICAL reading: any streak of normal readings is broken.
        state.consecutive_normal_count = 0

        if not state.alert_active:
            state.alert_active = True
            state.active_level = level
            return _threshold_event(device_id, level, co2_value)

        if level > state.active_level:
            state.active_level = level
            return _threshold_event(device_id, level, co2_value)

        # Same or lower severity than the already-active alert: cooldown.
        return None


engine = ThresholdEngine()
