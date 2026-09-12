// ESP32 + MQ135 sensor node firmware.
//
// Deliberately lightweight per the project architecture: read the MQ135
// -> convert to a CO2 estimate -> build the exact three-field JSON
// payload the gateway expects -> publish over MQTT -> wait 20 seconds ->
// repeat. No hashing, no blockchain, no heavy logic runs on the device -
// all of that lives in the Gateway, one layer up.
//
// One exception to "everything else lives in the Gateway": a local
// buzzer alarm (buzzer_alarm.h), by design - it's the physical demo
// alarm, and it must keep working when WiFi/MQTT/the gateway are down,
// which is only possible if it never depends on any of them. See
// updateBuzzerAlarm()'s call site in loop() below for exactly where it
// sits relative to the network-dependent code.
//
// Requires config.h (copy config.example.h and fill in real values - see
// README.md) and mq135_calibration.h (see that file for the CO2 math and
// the mandatory R0 calibration step before readings mean anything).

#include "config.h"
#include "mq135_calibration.h"
#include "buzzer_alarm.h"

#include <WiFi.h>

// Must be defined before including PubSubClient.h: the library's default
// buffer (128 bytes on older releases) is too small for this JSON
// payload plus MQTT framing overhead, and publishes are silently dropped
// if they don't fit rather than erroring - a well-known real-world
// gotcha with this library, worth guarding against here rather than
// discovering it during Phase 5 bring-up.
#define MQTT_MAX_PACKET_SIZE 256
#include <PubSubClient.h>

#include <ArduinoJson.h>

#include <time.h>
#include <sys/time.h>

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

const unsigned long PUBLISH_INTERVAL_MS = 20000;  // CLAUDE.md's specified real-world interval
const unsigned long WIFI_RECONNECT_TIMEOUT_MS = 15000;

void ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  Serial.println("WiFi disconnected, reconnecting...");
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  unsigned long start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < WIFI_RECONNECT_TIMEOUT_MS) {
    delay(250);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println();
    Serial.print("WiFi reconnected, IP: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("WiFi reconnect attempt timed out - will retry next loop.");
  }
}

void ensureMqttConnected() {
  if (mqttClient.connected()) {
    return;
  }

  Serial.print("Connecting to MQTT broker...");
  if (mqttClient.connect(DEVICE_ID)) {
    Serial.println(" connected.");
  } else {
    Serial.print(" failed, rc=");
    Serial.print(mqttClient.state());
    Serial.println(" - will retry next loop.");
  }
}

// Builds an ISO 8601 UTC timestamp with microsecond precision, e.g.
// "2026-08-24T06:12:27.975061Z" - matching the precision (though not the
// literal "+00:00" vs "Z" UTC suffix) of what
// tests/mqtt_test_publisher.py produces via Python's
// datetime.now(timezone.utc).isoformat(). Both are equally valid ISO
// 8601 UTC representations; sensor_timestamp is stored and hashed as an
// opaque string everywhere in the gateway (never parsed back into a
// datetime), so this difference has no functional effect - see
// Gateway/hashing.py.
String currentIsoTimestamp() {
  struct timeval tv;
  gettimeofday(&tv, NULL);

  struct tm utc;
  gmtime_r(&tv.tv_sec, &utc);

  char buf[40];
  snprintf(
      buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%06ldZ",
      utc.tm_year + 1900, utc.tm_mon + 1, utc.tm_mday,
      utc.tm_hour, utc.tm_min, utc.tm_sec, (long)tv.tv_usec
  );
  return String(buf);
}

void setup() {
  Serial.begin(115200);
  delay(200);

  pinMode(MQ135_PIN, INPUT);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);  // silent until a real reading says otherwise

  WiFi.mode(WIFI_STA);
  ensureWiFiConnected();

  // NTP sync - must happen once WiFi is up (it is, by this point), and
  // must succeed before the first reading is published. The ESP32 has no
  // real-time clock of its own, and sensor_timestamp is one of the three
  // canonical hash fields (device_id + co2 + sensor_timestamp per
  // CLAUDE.md) - publishing a wrong or placeholder timestamp here would
  // silently produce a record that looks fine but can never be correctly
  // re-verified later. There is no meaningful fallback if NTP fails, so
  // this blocks and retries indefinitely rather than proceeding with a
  // guessed time.
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");  // 0, 0: UTC directly, no DST offset
  Serial.print("Waiting for NTP time sync...");
  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    Serial.print(".");
    delay(500);
  }
  Serial.println(" done.");

  mqttClient.setServer(MQTT_BROKER_HOST, MQTT_BROKER_PORT);
}

void loop() {
  ensureWiFiConnected();
  ensureMqttConnected();
  mqttClient.loop();

  int rawAdc = analogRead(MQ135_PIN);
  float co2Ppm = mq135ReadPpm(rawAdc);

  // Buzzer alarm: called unconditionally, before anything below that
  // touches WiFi/MQTT, and does not read mqttClient.connected() or any
  // other network state - this is what "must work even if the network
  // is down" actually means in code, not just in the comment above it.
  updateBuzzerAlarm(BUZZER_PIN, co2Ppm);

  String timestamp = currentIsoTimestamp();

  // Exactly three fields, matching Gateway/mqtt_client.py's
  // REQUIRED_FIELDS and tests/mqtt_test_publisher.py's payload shape -
  // nothing extra. These three are also exactly CLAUDE.md's canonical
  // hash fields (device_id + co2 + sensor_timestamp); adding a fourth
  // field here would be harmless to the gateway's validation (which only
  // checks that these three are present) but should still be avoided so
  // this payload stays a faithful, minimal match to what the rest of the
  // system expects from a real sensor.
  JsonDocument doc;
  doc["device_id"] = DEVICE_ID;
  doc["co2"] = co2Ppm;
  doc["sensor_timestamp"] = timestamp;

  char payload[192];
  size_t payloadLen = serializeJson(doc, payload, sizeof(payload));

  if (mqttClient.connected()) {
    mqttClient.publish(MQTT_TOPIC, (const uint8_t *)payload, payloadLen);
    Serial.print("Published: ");
    Serial.println(payload);
  } else {
    Serial.println("MQTT not connected - skipping publish this cycle.");
  }

  delay(PUBLISH_INTERVAL_MS);
}
