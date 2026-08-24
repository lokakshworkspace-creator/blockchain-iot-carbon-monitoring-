"""
Simulates an ESP32+MQ135 sensor node for local testing of the gateway's MQTT
pipeline (Gateway/mqtt_client.py), without needing real hardware. Publishes
JSON payloads containing exactly device_id, co2, and sensor_timestamp -
matching what the real ESP32 firmware sends and CLAUDE.md's canonical hash
fields, nothing more.

Usage:
    python tests/mqtt_test_publisher.py --scenario normal
    python tests/mqtt_test_publisher.py --scenario warning --count 5
    python tests/mqtt_test_publisher.py --scenario offline

    # Exact, repeatable CO2 sequence (for threshold/hysteresis testing):
    python tests/mqtt_test_publisher.py --co2-sequence "700,1200,1200,2200,700,700,700"

    # Multiple concurrent devices: run separate instances (separate
    # terminals, or backgrounded) with different --device-id values.
    # Nothing else is needed - each instance is a fully independent MQTT
    # client publishing to the same shared topic, exactly like two real
    # ESP32 nodes would, and the gateway (mqtt_client.py/threshold.py/
    # device_status.py) is already keyed by device_id throughout:
    python tests/mqtt_test_publisher.py --device-id esp32-01 --co2-sequence "700,1200,1200,700"
    python tests/mqtt_test_publisher.py --device-id esp32-02 --co2-sequence "2200,2200,2200,700"
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Gateway"))
from config import settings  # noqa: E402

SCENARIOS = ("normal", "warning", "critical", "offline")
OFFLINE_MESSAGE_COUNT = 3


def _co2_for_scenario(scenario: str) -> float:
    warning = settings.co2_warning_threshold
    critical = settings.co2_critical_threshold

    if scenario in ("normal", "offline"):
        high = max(401.0, warning - 100)
        return round(random.uniform(400.0, high), 1)
    if scenario == "warning":
        low = warning + 10
        high = max(low + 1, critical - 10)
        return round(random.uniform(low, high), 1)
    if scenario == "critical":
        return round(random.uniform(critical + 50, critical + 800), 1)
    raise ValueError(f"unknown scenario: {scenario!r}")


def _build_reading(device_id: str, co2: float) -> dict:
    return {
        "device_id": device_id,
        "co2": co2,
        "sensor_timestamp": datetime.now(timezone.utc).isoformat(),
    }


def _iter_readings(args: argparse.Namespace) -> Iterator[tuple[int, int, dict]]:
    """Yields (index, total, reading) lazily so each reading's
    sensor_timestamp reflects when it was actually published, not
    precomputed before the --interval sleeps."""
    if args.co2_sequence is not None:
        values = [float(v.strip()) for v in args.co2_sequence.split(",") if v.strip()]
        total = len(values)
        for i, co2 in enumerate(values):
            yield i, total, _build_reading(args.device_id, co2)
        return

    total = OFFLINE_MESSAGE_COUNT if args.scenario == "offline" else args.count
    for i in range(total):
        yield i, total, _build_reading(args.device_id, _co2_for_scenario(args.scenario))


def main() -> None:
    parser = argparse.ArgumentParser(description="Simulate ESP32 CO2 sensor MQTT publishes.")
    parser.add_argument("--scenario", choices=SCENARIOS, default="normal")
    parser.add_argument("--device-id", default="esp32-01")
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Messages to publish (ignored for 'offline' and for --co2-sequence).",
    )
    parser.add_argument("--interval", type=float, default=2.0, help="Seconds to wait between publishes.")
    parser.add_argument(
        "--co2-sequence",
        default=None,
        help=(
            "Comma-separated exact CO2 values to publish in order, one per message "
            "(e.g. '700,1200,1200,2200,700,700,700'). Overrides --scenario/--count for "
            "deterministic threshold/hysteresis testing."
        ),
    )
    parser.add_argument("--broker-host", default=settings.mqtt_broker_host)
    parser.add_argument("--broker-port", type=int, default=settings.mqtt_broker_port)
    parser.add_argument("--topic", default=settings.mqtt_topic)
    args = parser.parse_args()

    client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    client.connect(args.broker_host, args.broker_port)
    client.loop_start()

    try:
        last_index = -1
        for i, total, reading in _iter_readings(args):
            client.publish(args.topic, json.dumps(reading))
            print(f"[{i + 1}/{total}] published to {args.topic}: {reading}")
            last_index = i
            if i < total - 1:
                time.sleep(args.interval)

        if args.co2_sequence is None and args.scenario == "offline":
            print(
                f"Scenario 'offline': stopped after {last_index + 1} messages "
                f"to simulate {args.device_id} going silent."
            )
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
