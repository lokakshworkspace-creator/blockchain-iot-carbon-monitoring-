#pragma once

// Copy this file to config.h and fill in real values for your network and
// device. config.h is gitignored (see the repo root .gitignore) so real
// WiFi credentials are never committed - the same private-credentials
// pattern as Gateway/.env vs Gateway/.env.example.

// --- WiFi ---
#define WIFI_SSID "your-wifi-ssid"
#define WIFI_PASSWORD "your-wifi-password"

// --- MQTT broker ---
// Must match Gateway/.env's MQTT_BROKER_HOST/MQTT_BROKER_PORT/MQTT_TOPIC
// exactly - the gateway subscribes to this exact topic and nothing else.
// MQTT_BROKER_HOST must be the LAN IP of the machine running the FastAPI
// gateway + Mosquitto (e.g. "192.168.1.100"), NOT "localhost" - the ESP32
// is a separate physical device on the network, so "localhost" would
// point it at itself.
#define MQTT_BROKER_HOST "192.168.1.100"
#define MQTT_BROKER_PORT 1883
#define MQTT_TOPIC "carbon/sensor01"

// --- Device identity ---
// Must be unique per physical sensor node. This value becomes every
// published reading's "device_id" field, and therefore is part of every
// hash and on-chain record for this device - do not change it after
// readings have been anchored, or later verification would look for a
// device that doesn't match past records.
#define DEVICE_ID "esp32-01"

// --- MQ135 analog input ---
// GPIO34 is an ADC1 pin (input-only, no internal pull-up/pull-down).
// ADC1 pins stay usable while WiFi is active, unlike ADC2 pins (GPIO0,
// 2, 4, 12-15, 25-27), which the WiFi radio can make unreliable to read
// - confirmed during Phase 1 planning specifically to avoid that conflict.
#define MQ135_PIN 34

// --- Buzzer alarm output ---
// GPIO25: a plain general-purpose digital output. Not a strapping pin
// (0/2/5/12/15, which must be in a specific state at boot) and not one
// of the input-only ADC pins (34-39, where MQ135_PIN already sits) - no
// conflict with the MQ135 wiring, and no boot-sequence or WiFi-radio
// interaction to worry about the way there is for an analog input pin.
//
// See buzzer_alarm.h for the alarm threshold/debounce logic - this is
// only the pin assignment. Assumes an ACTIVE buzzer module (sounds on a
// plain digital HIGH, has its own internal oscillator). If wiring a
// PASSIVE buzzer instead, swap buzzer_alarm.h's digitalWrite(buzzerPin,
// HIGH/LOW) calls for tone(BUZZER_PIN, <frequency>)/noTone(BUZZER_PIN).
#define BUZZER_PIN 25
