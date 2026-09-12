#pragma once

#include <Arduino.h>

// Local, network-independent CO2 alarm: drives a physical buzzer when the
// MQ135 reading crosses a threshold, entirely on-device. This must never
// depend on WiFi/MQTT/the gateway - it's the physical demo alarm, and the
// whole point of it existing is that it still works when the network is
// down. main.ino calls updateBuzzerAlarm() unconditionally, every loop()
// cycle, before anything MQTT-related - see that call site for why.
//
// Debounce/latch, mirroring the SPIRIT (not the exact mechanism) of
// Gateway/threshold.py's hysteresis, not a port of it:
// threshold.py opens an alert on a single above-threshold reading and
// requires CO2_HYSTERESIS_READINGS consecutive normal readings to
// resolve it. A physical buzzer sets a stricter bar in BOTH directions -
// CO2_ALARM_TRIGGER_READINGS consecutive above-threshold readings before
// it ever sounds, not just one - because a single noisy MQ135 reading
// setting off a loud physical alarm is a far more disruptive false
// positive than a dashboard badge flickering for one cycle.
// CO2_ALARM_RETRIGGER_COOLDOWN_MS is a second, independent guard: once
// silenced, the alarm can't re-sound for at least this long, so a CO2
// level oscillating right at the threshold boundary can't chatter the
// buzzer on/off every reading cycle even if it satisfies the consecutive-
// reading counts repeatedly in quick succession.

// --- Threshold ---
// Mirrors Gateway/.env's CO2_CRITICAL_THRESHOLD (the more serious of the
// two backend thresholds - WARNING is 1000ppm, CRITICAL is 2000ppm here).
// A physical alarm is tied to the "act now" level, not the "worth a
// dashboard badge" level. No remote config sync per the brief - if the
// backend's critical threshold ever changes, update this constant by
// hand to match; it is deliberately NOT fetched from the gateway.
static const float CO2_ALARM_THRESHOLD_PPM = 2000.0f;

// How many consecutive readings (each PUBLISH_INTERVAL_MS apart) must
// land on the same side of the threshold before the buzzer's state
// changes. 3 readings at the default 20s interval is 60s in either
// direction - deliberately slower to react than the gateway's own alert
// path, since this is the one thing in the whole system a false trigger
// is most disruptive for.
static const int CO2_ALARM_TRIGGER_READINGS = 3;
static const int CO2_ALARM_CLEAR_READINGS = 3;

// Minimum time the buzzer must stay silent after clearing before it is
// eligible to sound again, regardless of how quickly readings climb back
// above threshold.
//
// Must be strictly greater than the minimum time CO2_ALARM_TRIGGER_READINGS
// can possibly take to accumulate from a cold start right after clearing
// - (CO2_ALARM_TRIGGER_READINGS - 1) * the reading interval (20s in
// main.ino) - or this guard is a no-op: verify_buzzer_alarm_logic.py
// caught exactly this with an earlier 30000UL value here, since 3
// readings 20s apart take a minimum of 40s to accumulate, so a 30s
// cooldown had always already elapsed by the time the trigger condition
// could possibly be true again. 60s leaves real headroom above that 40s
// floor.
static const unsigned long CO2_ALARM_RETRIGGER_COOLDOWN_MS = 60000UL;

enum BuzzerAlarmState { BUZZER_ALARM_IDLE, BUZZER_ALARM_ACTIVE };

static BuzzerAlarmState buzzerAlarmState = BUZZER_ALARM_IDLE;
static int buzzerConsecutiveAbove = 0;
static int buzzerConsecutiveBelow = 0;
static unsigned long buzzerSilencedAtMs = 0;
static bool buzzerHasFiredOnce = false;

// Call once per reading, every loop() cycle, unconditionally - this is
// the entire point of keeping it out of the MQTT publish path.
//
// A NaN reading (e.g. before MQ135_R0 is calibrated - see
// mq135_calibration.h) compares false against the threshold under IEEE
// 754 float comparison rules, so an uncalibrated/garbage reading is
// always treated as "below threshold" and can never trigger the alarm -
// the same fail-safe-rather-than-false-positive posture
// R0_PLACEHOLDER_CALIBRATE_ME already takes for published readings.
inline void updateBuzzerAlarm(int buzzerPin, float co2Ppm) {
  bool above = co2Ppm >= CO2_ALARM_THRESHOLD_PPM;

  if (above) {
    buzzerConsecutiveAbove++;
    buzzerConsecutiveBelow = 0;
  } else {
    buzzerConsecutiveBelow++;
    buzzerConsecutiveAbove = 0;
  }

  if (buzzerAlarmState == BUZZER_ALARM_IDLE) {
    bool cooldownElapsed =
        !buzzerHasFiredOnce || (millis() - buzzerSilencedAtMs >= CO2_ALARM_RETRIGGER_COOLDOWN_MS);
    if (buzzerConsecutiveAbove >= CO2_ALARM_TRIGGER_READINGS && cooldownElapsed) {
      buzzerAlarmState = BUZZER_ALARM_ACTIVE;
      digitalWrite(buzzerPin, HIGH);
      Serial.println("CO2 ALARM: threshold crossed - buzzer ON");
    }
  } else {
    if (buzzerConsecutiveBelow >= CO2_ALARM_CLEAR_READINGS) {
      buzzerAlarmState = BUZZER_ALARM_IDLE;
      digitalWrite(buzzerPin, LOW);
      buzzerSilencedAtMs = millis();
      buzzerHasFiredOnce = true;
      Serial.println("CO2 ALARM: back below threshold - buzzer OFF");
    }
  }
}
