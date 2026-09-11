"""
Standalone MQTT device simulator (Phase 4) - NOT part of the FastAPI app
and imports nothing from it. Every message this script publishes is
indistinguishable, at the ingestion point (Gateway/mqtt_client.py), from
a real ESP32's: same topic, same three fields, same types, nothing added
to mark it as simulated. No gateway or ingestion code was touched to
build this - see the module docstring's last paragraph for why none was
needed.

Payload shape and topic come straight from ESP32/main.ino: one fixed
MQTT topic (settings.mqtt_topic) shared by every device, real or
simulated, with device_id as the only thing distinguishing one device's
readings from another's - not a per-device topic. Exactly three fields:
    {"device_id": str, "co2": float, "sensor_timestamp": <ISO-8601 UTC>}
matching Gateway/mqtt_client.py's REQUIRED_FIELDS and the same three
canonical hash fields CLAUDE.md specifies. The ISO timestamp's exact
suffix (this script emits "+00:00" like tests/mqtt_test_publisher.py;
the firmware emits "Z") makes no functional difference - see
ESP32/main.ino's currentIsoTimestamp() comment: sensor_timestamp is
stored and hashed as an opaque string everywhere, never parsed back into
a datetime.

Reads which devices to simulate from MongoDB directly (read-only, plain
pymongo - this script has no asyncio loop, so motor doesn't apply):
every document in the devices collection with is_hardware: false,
registered ahead of time via POST /api/admin/devices
(Gateway/routers/admin_devices.py). This script has no way to create
factories/devices itself, by design - register a handful with the admin
API first.

Why no gateway changes were needed: sensor_data.factory_id is never
populated at ingestion (Gateway/database.py's insert_sensor_record()
always writes factory_id=None - no router wires a real lookup into
Pipeline B, on purpose, per Phase 1). GET /api/readings and
GET /api/analytics (Phase 3) don't depend on that field either - their
region check resolves device_id -> devices.factory_id ->
factories.region_id fresh, from the devices registry, every request. So
a simulated reading is fully first-class the moment its device_id is
registered as a device - nothing about how the reading itself is
ingested, hashed, anchored, or region-scoped needed to change.

Usage (same venv as Gateway/ - paho-mqtt, pymongo, python-dotenv,
pydantic are already required there, nothing new to install):
    python simulator.py
    python simulator.py --interval 10 --spike-probability 0.15
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from pymongo import MongoClient
from pymongo.errors import PyMongoError

sys.path.insert(0, str(Path(__file__).resolve().parent / "Gateway"))
from config import settings  # noqa: E402

logging.basicConfig(level="INFO", format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("simulator")

# Matches ESP32/main.ino's PUBLISH_INTERVAL_MS (20000ms) - "a similar
# interval" to the real firmware, per the brief. Configurable via
# --interval for demo pacing (a faster tick makes a short demo window
# more legible without lying about what real hardware does).
DEFAULT_INTERVAL_SECONDS = 20.0
DEFAULT_SPIKE_PROBABILITY = 0.1
DEFAULT_REFRESH_SECONDS = 60.0

# Mild jitter around each device's own baseline - large enough to look
# like a real noisy sensor, small enough that only a genuine spike
# crosses into WARNING territory.
NOISE_BAND_PPM = 30.0
READING_FLOOR_PPM = 350.0


class SimulatedDevice:
    """One simulated device's own stable baseline, assigned once at first
    sight rather than re-randomized every tick - a device should read
    consistently between ticks, with an occasional spike being the
    interesting event rather than constant unpredictable jumps."""

    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        # A plausible "normal" band comfortably under the warning
        # threshold - same shape as tests/mqtt_test_publisher.py's own
        # "normal" scenario range, so a simulated device's baseline looks
        # like the same kind of reading a real ESP32 would report.
        high = max(READING_FLOOR_PPM + 1.0, settings.co2_warning_threshold - 150)
        self.baseline = round(random.uniform(READING_FLOOR_PPM, high), 1)

    def next_reading(self, spike_probability: float) -> float:
        if random.random() < spike_probability:
            # A clear excursion above the critical threshold, so
            # threshold.py's real alert logic actually fires - the point
            # of the spike is to prove the existing pipeline reacts to
            # simulated data exactly as it would to real hardware, with
            # no special-casing anywhere.
            return round(
                random.uniform(settings.co2_critical_threshold + 50, settings.co2_critical_threshold + 500), 1
            )
        noise = random.uniform(-NOISE_BAND_PPM, NOISE_BAND_PPM)
        return max(READING_FLOOR_PPM, round(self.baseline + noise, 1))


def _fetch_simulated_device_ids(mongo_client: MongoClient) -> list[str]:
    """Every devices document with is_hardware: false - see
    Gateway/routers/admin_devices.py. Read-only: this script never writes
    to the devices, factories, regions, or sensor_data collections -
    sensor_data is written exclusively by the gateway's own Pipeline B,
    the same as for a real ESP32."""
    db = mongo_client[settings.mongo_db_name]
    try:
        return [doc["device_id"] for doc in db["devices"].find({"is_hardware": False}, {"device_id": 1})]
    except PyMongoError:
        logger.exception("Could not read the devices registry from MongoDB")
        return []


def _build_payload(device_id: str, co2: float) -> dict:
    """Exactly the three fields ESP32/main.ino publishes, in the same
    shape - device_id (str), co2 (float), sensor_timestamp (ISO-8601 UTC
    string). No extra field marks this as simulated; that is the point -
    Gateway/mqtt_client.py cannot tell, and must not be made to."""
    return {
        "device_id": device_id,
        "co2": co2,
        "sensor_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def run(args: argparse.Namespace) -> None:
    mongo_client: MongoClient = MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)

    mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    # Same reconnect handling as Gateway/mqtt_client.py: exponential
    # backoff inside paho's own background thread, no custom retry loop
    # needed here either.
    mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
    mqtt_client.connect(args.broker_host, args.broker_port)
    mqtt_client.loop_start()
    logger.info("Connected to MQTT broker %s:%s, topic %s", args.broker_host, args.broker_port, args.topic)

    devices: dict[str, SimulatedDevice] = {}
    last_refresh = 0.0

    try:
        while True:
            now = time.monotonic()
            if now - last_refresh >= args.refresh_interval:
                device_ids = _fetch_simulated_device_ids(mongo_client)
                if not device_ids:
                    logger.warning(
                        "No simulated devices registered (devices collection has none with "
                        "is_hardware=false yet). Register some via POST /api/admin/devices - "
                        "they'll be picked up within %.0fs, no restart needed.",
                        args.refresh_interval,
                    )
                # Keep existing state for ids still present (a device's
                # baseline shouldn't reset just because the roster was
                # re-read); create new devices; silently drop ones no
                # longer registered.
                devices = {
                    device_id: devices.get(device_id, SimulatedDevice(device_id)) for device_id in device_ids
                }
                last_refresh = now

            for device in devices.values():
                co2 = device.next_reading(args.spike_probability)
                payload = _build_payload(device.device_id, co2)
                mqtt_client.publish(args.topic, json.dumps(payload))
                logger.info("Published %s: %.1f ppm", device.device_id, co2)

            time.sleep(args.interval)
    except KeyboardInterrupt:
        logger.info("Stopping (Ctrl+C)...")
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        mongo_client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate multiple CO2 sensor devices over MQTT.")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help=f"Seconds between publish ticks (default {DEFAULT_INTERVAL_SECONDS:.0f}, matching ESP32/main.ino).",
    )
    parser.add_argument(
        "--spike-probability",
        type=float,
        default=DEFAULT_SPIKE_PROBABILITY,
        help=f"Chance per device per tick of an above-critical-threshold reading (default {DEFAULT_SPIKE_PROBABILITY}).",
    )
    parser.add_argument(
        "--refresh-interval",
        type=float,
        default=DEFAULT_REFRESH_SECONDS,
        help=f"Seconds between re-reading the simulated-devices registry from MongoDB (default {DEFAULT_REFRESH_SECONDS:.0f}).",
    )
    parser.add_argument("--broker-host", default=settings.mqtt_broker_host)
    parser.add_argument("--broker-port", type=int, default=settings.mqtt_broker_port)
    parser.add_argument("--topic", default=settings.mqtt_topic)
    args = parser.parse_args()

    if not 0.0 <= args.spike_probability <= 1.0:
        parser.error("--spike-probability must be between 0 and 1")

    run(args)


if __name__ == "__main__":
    main()
