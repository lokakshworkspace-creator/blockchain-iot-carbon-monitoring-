"""
FastAPI entry point for the gateway. The MQTT bridge, threshold engine,
device-status tracking, Pipeline B (hash -> MongoDB), and WebSocket alert
delivery are all wired up here.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from config import settings
from database import insert_sensor_record
from device_status import tracker as device_status_tracker
from events import EventType, Severity, build_event
from hashing import generate_hash
from mqtt_client import MQTTBridge
from threshold import engine as threshold_engine
from websocket_manager import manager

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# How often the background task below checks for timed-out devices. Kept
# well under the smallest sensible DEVICE_TIMEOUT_SECONDS so an offline
# device is reported promptly without a dedicated scheduler (Phase 2's
# scheduler.py may end up owning this loop too, but not yet).
DEVICE_TIMEOUT_CHECK_INTERVAL_SECONDS = 2.0

# Pipeline A's entry point: MQTTBridge.on_message pushes here from paho's
# background thread; _consume_mqtt_messages below drains it on the main
# event loop, updates device-status, runs each reading through the
# threshold engine, and broadcasts whatever event(s) come back.
mqtt_queue: asyncio.Queue = asyncio.Queue()
mqtt_bridge = MQTTBridge(mqtt_queue)


async def _consume_mqtt_messages() -> None:
    while True:
        message = await mqtt_queue.get()

        try:
            device_id = message.get("device_id")

            online_event = device_status_tracker.record_message(device_id)
            if online_event is not None:
                await manager.broadcast(online_event.to_dict())

            threshold_event = threshold_engine.evaluate(device_id, message.get("co2"))
            if threshold_event is not None:
                await manager.broadcast(threshold_event.to_dict())
        except Exception:
            # Pipeline A must never die from one bad reading - log and keep
            # draining the queue, per CLAUDE.md's "minimal failure handling".
            logger.exception("Pipeline A failed to process MQTT message: %r", message)

        # Pipeline B (background): hashing + MongoDB. Spawned as its own task
        # rather than awaited here, so it runs concurrently with - and can
        # never delay - Pipeline A's WebSocket alert above.
        _spawn_pipeline_b(message)


async def _process_pipeline_b(message: dict) -> None:
    device_id = message.get("device_id")
    try:
        co2 = message.get("co2")
        sensor_timestamp = message.get("sensor_timestamp")

        hash_value = generate_hash(device_id, co2, sensor_timestamp)
        hash_event = build_event(
            EventType.HASH_GENERATED,
            message=f"{device_id} reading hashed: {hash_value[:12]}...",
            severity=Severity.INFO,
            device_id=device_id,
        )
        await manager.broadcast(hash_event.to_dict())

        record_id = await insert_sensor_record(
            device_id=device_id,
            co2=co2,
            sensor_timestamp=sensor_timestamp,
            gateway_received_timestamp=message.get("gateway_received_timestamp"),
            hash_value=hash_value,
        )
        stored_event = build_event(
            EventType.DATABASE_STORED,
            message=f"{device_id} reading stored (record {record_id})",
            severity=Severity.INFO,
            device_id=device_id,
        )
        await manager.broadcast(stored_event.to_dict())
    except Exception as exc:
        # Covers a hashing or a DB failure alike (DB is by far the likelier
        # one in practice) - Pipeline A above has already run and broadcast
        # its own alert by this point regardless of what happens here.
        logger.exception("Pipeline B failed to process message: %r", message)
        error_event = build_event(
            EventType.DATABASE_ERROR,
            message=f"{device_id} Pipeline B failed: {exc}",
            severity=Severity.CRITICAL,
            device_id=device_id,
        )
        await manager.broadcast(error_event.to_dict())


_pipeline_b_tasks: set[asyncio.Task] = set()


def _spawn_pipeline_b(message: dict) -> None:
    task = asyncio.create_task(_process_pipeline_b(message))
    _pipeline_b_tasks.add(task)
    task.add_done_callback(_pipeline_b_tasks.discard)


async def _check_device_timeouts_periodically() -> None:
    while True:
        await asyncio.sleep(DEVICE_TIMEOUT_CHECK_INTERVAL_SECONDS)
        for event in device_status_tracker.check_timeouts():
            await manager.broadcast(event.to_dict())


@asynccontextmanager
async def lifespan(app: FastAPI):
    mqtt_bridge.start()
    consumer_task = asyncio.create_task(_consume_mqtt_messages())
    device_timeout_task = asyncio.create_task(_check_device_timeouts_periodically())
    try:
        yield
    finally:
        consumer_task.cancel()
        device_timeout_task.cancel()
        for task in list(_pipeline_b_tasks):
            task.cancel()
        mqtt_bridge.stop()


app = FastAPI(title="Carbon Emission Gateway", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "mqtt_broker": f"{settings.mqtt_broker_host}:{settings.mqtt_broker_port}",
        "mqtt_topic": settings.mqtt_topic,
    }


@app.get("/devices/status")
def devices_status() -> list[dict]:
    return device_status_tracker.snapshot()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    test_event = build_event(
        EventType.TEST_MESSAGE,
        message="WebSocket connected to gateway",
        severity=Severity.INFO,
    )
    await manager.broadcast(test_event.to_dict())
    try:
        while True:
            # Phase 1 dashboard clients are receive-only; this just detects
            # disconnects (a closed socket raises WebSocketDisconnect here).
            await websocket.receive_text()
    except WebSocketDisconnect:
        await manager.disconnect(websocket)
