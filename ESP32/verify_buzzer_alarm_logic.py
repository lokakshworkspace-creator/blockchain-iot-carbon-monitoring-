"""
Standalone sanity check for buzzer_alarm.h's debounce/latch/cooldown
state machine, reimplemented here in Python so its LOGIC can be verified
without any ESP32 hardware or Arduino toolchain - the same reason
verify_mq135_calibration_math.py exists for the CO2 math (see that
file's docstring; no Arduino toolchain was available while writing
either).

This does not and cannot verify the firmware actually compiles, that
GPIO25 drives a real buzzer, or real MQ135 reading noise - only that the
trigger/clear/cooldown state transitions in updateBuzzerAlarm() are
internally self-consistent. Every constant and the state machine's shape
below must be kept in sync with buzzer_alarm.h by hand - there is no
shared source between the C++ header and this script.

Run: python ESP32/verify_buzzer_alarm_logic.py
"""

import math

# --- Constants: must match buzzer_alarm.h exactly ---
CO2_ALARM_THRESHOLD_PPM = 2000.0
CO2_ALARM_TRIGGER_READINGS = 3
CO2_ALARM_CLEAR_READINGS = 3
CO2_ALARM_RETRIGGER_COOLDOWN_MS = 60000


class BuzzerAlarm:
    """Line-for-line port of buzzer_alarm.h's updateBuzzerAlarm() and its
    module-level state variables - a fresh instance per scenario mirrors
    a fresh boot (all state variables zero-initialized)."""

    def __init__(self) -> None:
        self.active = False
        self.consecutive_above = 0
        self.consecutive_below = 0
        self.silenced_at_ms = 0
        self.has_fired_once = False
        self.buzzer_on = False  # what digitalWrite(buzzerPin, ...) would have set

    def update(self, co2_ppm: float, now_ms: int) -> None:
        above = co2_ppm >= CO2_ALARM_THRESHOLD_PPM  # NaN >= anything is False, same as C++ IEEE 754

        if above:
            self.consecutive_above += 1
            self.consecutive_below = 0
        else:
            self.consecutive_below += 1
            self.consecutive_above = 0

        if not self.active:
            cooldown_elapsed = not self.has_fired_once or (now_ms - self.silenced_at_ms >= CO2_ALARM_RETRIGGER_COOLDOWN_MS)
            if self.consecutive_above >= CO2_ALARM_TRIGGER_READINGS and cooldown_elapsed:
                self.active = True
                self.buzzer_on = True
        else:
            if self.consecutive_below >= CO2_ALARM_CLEAR_READINGS:
                self.active = False
                self.buzzer_on = False
                self.silenced_at_ms = now_ms
                self.has_fired_once = True


def check(label: str, condition: bool) -> None:
    print(f"{'PASS' if condition else 'FAIL'}  {label}")
    if not condition:
        raise SystemExit(1)


READING_INTERVAL_MS = 20000  # matches main.ino's PUBLISH_INTERVAL_MS


def feed(alarm: BuzzerAlarm, readings, start_ms: int = 0) -> None:
    """Feeds a sequence of ppm values, one per simulated 20s tick."""
    for i, ppm in enumerate(readings):
        alarm.update(ppm, start_ms + i * READING_INTERVAL_MS)


def main() -> None:
    above = CO2_ALARM_THRESHOLD_PPM + 500
    below = CO2_ALARM_THRESHOLD_PPM - 500

    # --- Check 1: a single above-threshold reading must not trigger ---
    alarm = BuzzerAlarm()
    feed(alarm, [below, below, above, below, below])
    check("a single above-threshold reading alone never sounds the buzzer", not alarm.buzzer_on)

    # --- Check 2: exactly CO2_ALARM_TRIGGER_READINGS consecutive readings triggers, on that reading ---
    alarm = BuzzerAlarm()
    feed(alarm, [above] * (CO2_ALARM_TRIGGER_READINGS - 1))
    check(f"{CO2_ALARM_TRIGGER_READINGS - 1} consecutive readings: still silent", not alarm.buzzer_on)
    alarm.update(above, (CO2_ALARM_TRIGGER_READINGS - 1) * READING_INTERVAL_MS)
    check(f"the {CO2_ALARM_TRIGGER_READINGS}rd consecutive reading sounds it", alarm.buzzer_on)

    # --- Check 3: a broken streak resets the consecutive-above count ---
    alarm = BuzzerAlarm()
    feed(alarm, [above, above, below, above, above])  # streak broken once, never reaches 3 again
    check("a streak broken by one normal reading never accumulates across the gap", not alarm.buzzer_on)

    # --- Check 4: once active, fewer than CO2_ALARM_CLEAR_READINGS normal readings don't clear it ---
    alarm = BuzzerAlarm()
    feed(alarm, [above, above, above])
    check("active after 3 consecutive above-threshold readings", alarm.buzzer_on)
    feed(alarm, [below] * (CO2_ALARM_CLEAR_READINGS - 1), start_ms=3 * READING_INTERVAL_MS)
    check(f"still active after only {CO2_ALARM_CLEAR_READINGS - 1} consecutive normal readings", alarm.buzzer_on)
    alarm.update(below, (3 + CO2_ALARM_CLEAR_READINGS - 1) * READING_INTERVAL_MS)
    check(f"clears on the {CO2_ALARM_CLEAR_READINGS}rd consecutive normal reading", not alarm.buzzer_on)

    # --- Check 5: cooldown blocks an immediate re-trigger even if readings go straight back above threshold ---
    alarm = BuzzerAlarm()
    feed(alarm, [above, above, above])  # triggers at t=40000ms (3rd reading, index 2)
    feed(alarm, [below, below, below], start_ms=3 * READING_INTERVAL_MS)  # clears at t=100000ms
    silenced_at = alarm.silenced_at_ms
    check("alarm cleared and recorded a silence timestamp", not alarm.buzzer_on and alarm.has_fired_once)
    # Immediately try to re-trigger, well inside the cooldown window - the
    # 3rd reading here lands at silenced_at + 40001ms, comfortably short
    # of the 60000ms cooldown boundary.
    feed(alarm, [above, above, above], start_ms=silenced_at + 1)
    check(
        "3 more consecutive above-threshold readings inside the cooldown window do NOT re-sound it",
        not alarm.buzzer_on,
    )
    # Advance past the cooldown and feed the same streak again.
    feed(alarm, [above, above, above], start_ms=silenced_at + CO2_ALARM_RETRIGGER_COOLDOWN_MS + READING_INTERVAL_MS)
    check("the same streak AFTER the cooldown elapses does re-sound it", alarm.buzzer_on)

    # --- Check 6: NaN readings (uncalibrated R0) never trigger ---
    alarm = BuzzerAlarm()
    feed(alarm, [math.nan] * (CO2_ALARM_TRIGGER_READINGS + 5))
    check("NaN readings never satisfy the threshold comparison, so the alarm never sounds", not alarm.buzzer_on)

    # --- Check 7: a reading exactly at the threshold counts as "above" (>=, not >) ---
    alarm = BuzzerAlarm()
    feed(alarm, [CO2_ALARM_THRESHOLD_PPM] * CO2_ALARM_TRIGGER_READINGS)
    check("a reading exactly AT the threshold counts toward triggering (>=)", alarm.buzzer_on)

    print("\nAll buzzer alarm debounce/latch/cooldown logic checks passed.")
    print(
        "Reminder: this only proves the STATE MACHINE is self-consistent - it does\n"
        "not and cannot verify the firmware compiles, that GPIO25 actually drives a\n"
        "real buzzer, or how real MQ135 reading noise behaves on physical hardware."
    )


if __name__ == "__main__":
    main()
