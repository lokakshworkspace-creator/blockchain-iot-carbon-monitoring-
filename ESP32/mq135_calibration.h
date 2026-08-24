#pragma once

#include <math.h>

// MQ135 CO2 estimation math: raw 12-bit ADC reading -> voltage -> sensor
// resistance (Rs) -> Rs/R0 ratio -> CO2 ppm, using the standard MQ135
// load-resistor circuit and the widely-published MQ135 CO2 datasheet
// curve fit (the same PARA/PARB/ATMOCO2 constants used by the common
// open-source MQ135 Arduino libraries this project's math was checked
// against - see ESP32/verify_mq135_calibration_math.py). Exact curve
// constants can vary slightly by sensor batch/manufacturer - treat these
// as a documented, checkable starting point to cross-reference against
// this specific MQ135 unit's own datasheet during Phase 5 bring-up, not
// as an exact guarantee.

// --- Circuit constants (must match the physical wiring in README.md) ---

// Supply voltage feeding the MQ135 module, and therefore the reference
// voltage of the resistor divider the AO pin sits in. README.md wires
// VCC to the ESP32's 3.3V rail (not 5V), matching the ESP32 ADC's own
// 3.3V reference. If the physical module is ever wired to 5V instead,
// this constant AND the raw ADC readings themselves would both need
// revisiting (a 5V signal would also risk exceeding the ESP32 ADC pin's
// safe input range).
static const float MQ135_VCC = 3.3f;

// Standard load resistor value used on most MQ135 breakout modules -
// check the specific module's silkscreen/datasheet before trusting this;
// some modules use 20k instead of 10k.
static const float MQ135_RL_KOHM = 10.0f;

// ESP32's ADC is 12-bit: raw analogRead() values range 0-4095.
static const int MQ135_ADC_MAX_RAW = 4095;

// --- CO2 curve constants (MQ135 datasheet log-log fit) ---
static const float MQ135_PARA = 116.6020682f;
static const float MQ135_PARB = 2.769034857f;

// Assumed CO2 concentration of the "clean air" used as the calibration
// reference point (typical outdoor ambient CO2, per the same datasheet
// curve these constants come from).
static const float MQ135_ATMOCO2_PPM = 397.13f;

// --- R0: THE ONE VALUE THAT MUST BE CALIBRATED PER PHYSICAL SENSOR ---
//
// R0 is this specific MQ135 unit's sensor resistance in known-clean air,
// scaled by the curve fit above (see mq135CalibrateR0() below). It varies
// sensor-to-sensor and drifts as the sensor burns in, so there is no
// universal correct value - it MUST be measured for this exact unit
// after burn-in, not assumed or copied from a datasheet/tutorial.
//
// THIS PLACEHOLDER IS DELIBERATELY AN IMPOSSIBLE VALUE: a resistance
// reference can never be negative. Every ppm reading computed while this
// is still -1.0 will come out as NaN (a negative base raised to
// MQ135_PARB's non-integer power is undefined) - that is intentional.
// A "reasonable-looking" uncalibrated reading would be far more
// dangerous than an obviously-broken one, since it could easily be
// mistaken for a real measurement instead of caught immediately.
//
// DO NOT replace this with any value you have not personally measured
// using mq135CalibrateR0() below, on THIS physical sensor, after the
// 24-48h burn-in period described in README.md.
static const float R0_PLACEHOLDER_CALIBRATE_ME = -1.0f;

// The value main.ino's readings actually use. Change ONLY this line, to
// the real number mq135CalibrateR0() gives you for this sensor - do not
// edit R0_PLACEHOLDER_CALIBRATE_ME itself, so its name keeps meaning
// "uncalibrated" for the next person (or the next sensor) who reads it.
static const float MQ135_R0 = R0_PLACEHOLDER_CALIBRATE_ME;

// Raw ADC (0-4095) -> voltage at the AO pin.
inline float mq135RawToVoltage(int rawAdc) {
  return (rawAdc / (float)MQ135_ADC_MAX_RAW) * MQ135_VCC;
}

// Voltage -> sensor resistance Rs, from the standard MQ135 voltage-divider
// circuit: Rs = RL * (Vc - Vout) / Vout.
inline float mq135VoltageToRs(float voltage) {
  if (voltage <= 0.0f) {
    return INFINITY;  // avoid a division by zero if the ADC ever reads exactly 0
  }
  return MQ135_RL_KOHM * (MQ135_VCC - voltage) / voltage;
}

// Rs/R0 ratio -> CO2 ppm, via the datasheet curve fit:
// ppm = PARA * (Rs/R0)^(-PARB).
inline float mq135RsToPpm(float rs, float r0) {
  return MQ135_PARA * pow(rs / r0, -MQ135_PARB);
}

// Full pipeline: raw ADC -> ppm, using the calibrated MQ135_R0 above.
// This is the one function main.ino's loop() actually calls.
inline float mq135ReadPpm(int rawAdc) {
  float voltage = mq135RawToVoltage(rawAdc);
  float rs = mq135VoltageToRs(voltage);
  return mq135RsToPpm(rs, MQ135_R0);
}

// --- R0 calibration procedure ---
//
// Run ONCE, manually, during Phase 5 bring-up - NOT part of the main
// loop, and not called from setup()/loop() anywhere in main.ino. Wire up
// a temporary sketch (or a serial command) that calls this with a fresh
// raw ADC reading while the sensor sits in known-clean outdoor air
// (~397ppm, the MQ135_ATMOCO2_PPM constant above) after the 24-48h
// burn-in period in README.md, then paste the printed result into
// MQ135_R0 above (replacing R0_PLACEHOLDER_CALIBRATE_ME) and reflash.
inline float mq135CalibrateR0(int rawAdcInCleanAir) {
  float voltage = mq135RawToVoltage(rawAdcInCleanAir);
  float rs = mq135VoltageToRs(voltage);
  return rs * pow(MQ135_ATMOCO2_PPM / MQ135_PARA, 1.0f / MQ135_PARB);
}
