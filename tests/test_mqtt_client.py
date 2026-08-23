"""
Defensive tests for Gateway/mqtt_client.py's on_message handler, exercised
directly with a fake paho MQTTMessage - no live broker needed. These prove
that malformed input is logged and dropped rather than crashing the
background MQTT thread (which would silently kill message delivery with no
obvious symptom other than the dashboard going quiet).
"""

import asyncio
import json
import logging

from mqtt_client import MQTTBridge


class FakeMQTTMessage:
    """Stand-in for paho.mqtt.client.MQTTMessage - on_message only reads
    .topic and .payload, so a full paho message object isn't needed."""

    def __init__(self, topic: str, payload: bytes) -> None:
        self.topic = topic
        self.payload = payload


def test_on_message_drops_invalid_json_without_raising(caplog):
    queue: asyncio.Queue = asyncio.Queue()
    bridge = MQTTBridge(queue)
    msg = FakeMQTTMessage("carbon/sensor01", b"{not valid json at all")

    with caplog.at_level(logging.WARNING):
        bridge._on_message(client=None, userdata=None, msg=msg)  # must not raise

    assert queue.empty()
    assert "unparsable" in caplog.text


def test_on_message_drops_payload_missing_required_field_without_raising(caplog):
    queue: asyncio.Queue = asyncio.Queue()
    bridge = MQTTBridge(queue)
    # Valid JSON, but missing device_id.
    payload = {"co2": 450.0, "sensor_timestamp": "2026-08-23T00:00:00+00:00"}
    msg = FakeMQTTMessage("carbon/sensor01", json.dumps(payload).encode("utf-8"))

    with caplog.at_level(logging.WARNING):
        bridge._on_message(client=None, userdata=None, msg=msg)  # must not raise

    assert queue.empty()
    assert "missing required field" in caplog.text
    assert "device_id" in caplog.text
