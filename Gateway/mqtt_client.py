"""
Async-safe bridge between paho-mqtt (a synchronous client running its own
network thread via loop_start()) and the FastAPI/asyncio side of the gateway.

paho's on_connect/on_disconnect/on_message callbacks fire on that background
thread, never on the asyncio event loop - so they must never `await`
directly. Each callback instead hands its result to the event loop via
asyncio.run_coroutine_threadsafe(), which schedules a coroutine to run on
the loop from another thread. The consumer (app.py) then awaits the queue
on the main event loop like any other async code.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from config import settings

logger = logging.getLogger(__name__)

# The only fields Pipeline A/B actually depend on downstream (threshold
# evaluation and, later, hashing). Anything else in the payload is passed
# through untouched.
REQUIRED_FIELDS = ("device_id", "co2", "sensor_timestamp")


class MQTTBridge:
    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._loop: asyncio.AbstractEventLoop | None = None

        self._client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        # Exponential backoff between reconnect attempts, handled entirely
        # inside paho's own network thread - no custom retry loop needed.
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    def start(self) -> None:
        """Must be called from a running event loop (e.g. FastAPI lifespan)."""
        self._loop = asyncio.get_running_loop()
        # connect_async + loop_start lets the broker be unreachable at
        # startup (or drop later) without raising here or blocking the
        # gateway - paho retries in the background using the delay above.
        self._client.connect_async(settings.mqtt_broker_host, settings.mqtt_broker_port)
        self._client.loop_start()
        logger.info(
            "MQTT bridge starting: connecting to %s:%s, topic %s",
            settings.mqtt_broker_host,
            settings.mqtt_broker_port,
            settings.mqtt_topic,
        )

    def stop(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()

    def _on_connect(self, client: mqtt.Client, userdata, flags, reason_code, properties=None) -> None:
        if reason_code.is_failure:
            logger.error("MQTT connect failed: %s", reason_code)
            return
        logger.info("MQTT connected, subscribing to %s", settings.mqtt_topic)
        client.subscribe(settings.mqtt_topic)

    def _on_disconnect(self, client: mqtt.Client, userdata, disconnect_flags, reason_code, properties=None) -> None:
        logger.warning("MQTT disconnected (%s); paho will reconnect automatically", reason_code)

    def _on_message(self, client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            logger.warning("Dropping unparsable MQTT message on %s: %r", msg.topic, msg.payload)
            return

        if not isinstance(payload, dict):
            logger.warning("Dropping MQTT message on %s: expected a JSON object, got %r", msg.topic, payload)
            return

        missing_fields = [name for name in REQUIRED_FIELDS if name not in payload]
        if missing_fields:
            logger.warning(
                "Dropping MQTT message on %s missing required field(s) %s: %r",
                msg.topic,
                missing_fields,
                payload,
            )
            return

        # Kept separate from sensor_timestamp per CLAUDE.md: used for latency
        # display only, never part of the SHA-256 hash in Pipeline B.
        payload["gateway_received_timestamp"] = datetime.now(timezone.utc).isoformat()

        if self._loop is None:
            logger.warning("Dropping MQTT message received before MQTTBridge.start() ran")
            return

        asyncio.run_coroutine_threadsafe(self._queue.put(payload), self._loop)
