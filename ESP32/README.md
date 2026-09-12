# ESP32 + MQ135 Sensor Node

Firmware for the sensing layer: reads the MQ135, estimates CO2 ppm, and
publishes it over MQTT to the gateway. Written and reviewed ahead of
Phase 5's physical hardware bring-up (no board exists yet at the time
these files were written) - see the "What's verified vs. what isn't"
note at the bottom before trusting anything here on real hardware.

## Wiring

| MQ135 pin | ESP32 pin |
|---|---|
| VCC | 3.3V |
| GND | GND |
| AO (analog out) | GPIO34 |
| DO (digital out) | not connected - unused |

| Buzzer pin | ESP32 pin |
|---|---|
| + (signal) | GPIO25 |
| - (GND) | GND |

GPIO34 is an ADC1, input-only pin. ADC1 stays usable while WiFi is
active, unlike ADC2 pins (GPIO0, 2, 4, 12-15, 25-27), which the WiFi
radio can make unreliable to read from - this was confirmed during
Phase 1 planning specifically to avoid that conflict.

GPIO25 is a plain digital output with no such constraint - it's not a
strapping pin and not one of the input-only ADC pins GPIO34 already
occupies, so it doesn't interact with either the MQ135 wiring or WiFi.

MQ135_VCC in `mq135_calibration.h` assumes the module is powered from
3.3V, matching this wiring and the ESP32 ADC's own 3.3V reference. If a
particular breakout module is ever wired to 5V instead, both that
constant and the raw ADC readings would need revisiting - and a 5V
signal risks exceeding the ESP32 ADC pin's safe input range, so don't
do this without a voltage divider.

## Buzzer alarm

A physical CO2 alarm, entirely local to the device - see
`buzzer_alarm.h`. Deliberately independent of WiFi/MQTT/the gateway: it
reads directly off the same `co2Ppm` value the main loop computes every
cycle, before any network code runs, so it keeps working exactly the
same whether WiFi is up, down, or was never configured at all.

- Threshold: `CO2_ALARM_THRESHOLD_PPM` in `buzzer_alarm.h`, currently
  `2000.0f` to mirror `Gateway/.env`'s `CO2_CRITICAL_THRESHOLD`. There is
  no remote config sync by design (per the project's "no retry
  frameworks, no remote config systems" stance) - if the backend's
  critical threshold is ever changed, update this constant by hand to
  match and reflash.
- Debounce: the buzzer needs `CO2_ALARM_TRIGGER_READINGS` (default 3)
  consecutive above-threshold readings before it ever sounds, and
  `CO2_ALARM_CLEAR_READINGS` (default 3) consecutive below-threshold
  readings before it goes silent again - at the default 20s publish
  interval, that's roughly a minute of sustained readings in either
  direction, not a single noisy sample. `CO2_ALARM_RETRIGGER_COOLDOWN_MS`
  (default 60s - deliberately longer than the ~40s minimum it takes 3
  readings to accumulate, or this guard would never actually do anything;
  see the comment on this constant in `buzzer_alarm.h`) additionally
  keeps it from re-sounding immediately after going silent, so a CO2
  level hovering right at the threshold can't chatter the buzzer on and
  off.
- Assumes an **active** buzzer module (sounds on a plain digital HIGH). If
  wiring a passive buzzer instead, see `config.example.h`'s `BUZZER_PIN`
  comment for the one-line swap (`tone()`/`noTone()` instead of
  `digitalWrite()`).

## Required libraries (Arduino IDE)

Install via Arduino IDE's Boards Manager / Library Manager:

- **Board package:** `esp32` by Espressif Systems (Boards Manager)
- **PubSubClient** by Nick O'Leary
- **ArduinoJson** version **7.x** or newer, by Benoit Blanchon (this
  firmware uses the current `JsonDocument` API, not the older
  `StaticJsonDocument` from ArduinoJson 6)

## Setup

1. Copy `config.example.h` to `config.h` and fill in:
   - Your real WiFi SSID/password
   - `MQTT_BROKER_HOST` - the **LAN IP** of the machine running the
     FastAPI gateway + Mosquitto (not `localhost` - the ESP32 is a
     separate physical device on the network)
   - `MQTT_BROKER_PORT` / `MQTT_TOPIC` - must match `Gateway/.env`'s
     `MQTT_BROKER_PORT` / `MQTT_TOPIC` exactly
   - `DEVICE_ID` - unique per physical sensor node

   `config.h` is gitignored, the same private-credentials pattern as
   `Gateway/.env` vs `Gateway/.env.example` - never commit real WiFi
   credentials.

2. Open `main.ino` in the Arduino IDE with the ESP32 board package
   selected, and flash it to the device.

## Phase 5 bring-up sequence

This firmware expects to be brought up in this exact order - readings
published before step 4 below are not meaningful CO2 measurements, even
though they will look like valid JSON and pass the gateway's validation:

1. **Flash** the firmware (with `config.h` filled in) to the ESP32.
2. **Burn in the MQ135 for 24-48 hours** with the sensor powered and
   exposed to normal air, before trusting any reading from it. MQ135
   sensors need this warm-up period for their internal heater element
   and sensing layer to stabilize; readings taken before this are
   unreliable regardless of calibration.
3. **Run the R0 calibration utility** - `mq135CalibrateR0()` in
   `mq135_calibration.h` - once, manually, with the sensor sitting in
   known-clean outdoor air. This is not part of the main loop; wire up a
   temporary sketch (or add a one-off serial command) that reads the raw
   ADC value and passes it to `mq135CalibrateR0()`, and print the result.
4. **Paste the resulting R0 value** into `mq135_calibration.h`, replacing
   the `MQ135_R0` line's reference to `R0_PLACEHOLDER_CALIBRATE_ME` (leave
   `R0_PLACEHOLDER_CALIBRATE_ME` itself untouched, so its name keeps
   meaning "uncalibrated" for the next sensor or the next person who
   reads it - only change what `MQ135_R0` is set to).
5. **Reflash** with the real R0 in place.
6. **Only now** treat published readings as real CO2 estimates.

Skipping straight to step 6 will not fail loudly at the network/JSON
level - it will silently publish NaN-derived garbage as `co2`, since
`R0_PLACEHOLDER_CALIBRATE_ME` is deliberately an impossible negative
resistance value precisely so uncalibrated output doesn't look
plausible. Watch the Serial monitor output during bring-up; a real
reading should be a normal-looking number, not `nan`.

## Troubleshooting notes for Phase 5

- If MQTT publishes appear to silently do nothing (no error, but nothing
  arrives at the gateway), double check `MQTT_MAX_PACKET_SIZE` - some
  PubSubClient releases default to a 128-byte buffer, too small for this
  JSON payload plus MQTT framing. `main.ino` already defines this to 256
  before including the library, but confirm your installed PubSubClient
  version respects that override.
- If the gateway never sees `DEVICE_ONLINE` for this device, check
  `MQTT_BROKER_HOST` is the gateway machine's actual LAN IP (not
  `localhost`, `127.0.0.1`, or a stale IP from a previous DHCP lease) and
  that both devices are on the same network/subnet.

## What's verified vs. what isn't (written before any hardware exists)

**Verified now, without hardware:**

- The published JSON payload's three fields (`device_id`, `co2`,
  `sensor_timestamp`) match `Gateway/mqtt_client.py`'s `REQUIRED_FIELDS`
  and the shape `tests/mqtt_test_publisher.py` sends, by direct
  code comparison.
- The MQ135 ADC-to-ppm math's *logic* (the voltage/Rs/ppm formulas and
  the R0 calibration formula's self-consistency) is checked by
  `verify_mq135_calibration_math.py` in this folder - a standalone
  Python reimplementation of the same formulas with known reference
  values, runnable right now with `python ESP32/verify_mq135_calibration_math.py`.
- The buzzer alarm's debounce/latch/cooldown state machine
  (`buzzer_alarm.h`) is checked the same way, by
  `verify_buzzer_alarm_logic.py` - a Python port of `updateBuzzerAlarm()`
  exercised against 12 scenarios (won't trigger on one noisy reading,
  triggers on the Nth consecutive reading, a broken streak doesn't
  accumulate, clears after N consecutive normal readings, the cooldown
  genuinely blocks an immediate re-trigger and expires correctly, NaN
  readings never trigger, an exactly-at-threshold reading counts).
  Writing this test is what caught a real bug before it ever reached a
  board: the cooldown constant was initially shorter than the minimum
  time the trigger-reading count can possibly take to accumulate, which
  would have made it a silent no-op forever - fixed to a value with real
  headroom above that floor, with the reasoning left as a comment on the
  constant. Runnable right now with
  `python ESP32/verify_buzzer_alarm_logic.py`.

**Genuinely untestable until Phase 5's physical bring-up:**

- Whether this actually compiles against a real ESP32 board package and
  library set - no Arduino toolchain was available while writing this,
  and none of it has been compiled.
- Real ADC readings from a real MQ135 - the formula's logic is checked,
  but not against a real sensor's real output.
- Real WiFi/MQTT reconnect behavior on the actual device.
- The real R0 constant for any specific physical sensor unit - this
  cannot be determined without the sensor in hand, burned in, and
  calibrated in real clean air.
- Whether GPIO25 actually drives a real buzzer module the way assumed
  (active buzzer, sounds on a plain digital HIGH) - untestable without
  the physical buzzer in hand.
