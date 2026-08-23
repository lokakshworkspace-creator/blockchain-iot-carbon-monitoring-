"""
FastAPI entry point for the gateway. The MQTT bridge, threshold engine,
device-status tracking, Pipeline B (hash -> MongoDB -> Sepolia), and
WebSocket alert delivery are all wired up here.
"""

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from blockchain import client as blockchain_client
from config import settings
from database import count_records, get_recent_records, insert_sensor_record, update_blockchain_info
from device_status import tracker as device_status_tracker
from events import EventType, Severity, build_event
from hashing import generate_hash
from mqtt_client import MQTTBridge
from threshold import engine as threshold_engine
from verification import verify_record
from websocket_manager import manager

logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# How often the background task below checks for timed-out devices. Kept
# well under the smallest sensible DEVICE_TIMEOUT_SECONDS so an offline
# device is reported promptly without a dedicated scheduler (Phase 2's
# scheduler.py may end up owning this loop too, but not yet).
DEVICE_TIMEOUT_CHECK_INTERVAL_SECONDS = 2.0

# GET /records paging. The cap exists so a stray ?limit=100000 can't pull
# the whole collection into memory and stall the event loop.
DEFAULT_RECORDS_LIMIT = 20
MAX_RECORDS_LIMIT = 200

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

            # Pure telemetry, emitted for every message that passed
            # mqtt_client.py's validation and before either pipeline does
            # anything with it. The dashboard's live chart needs a data
            # point per reading, whereas threshold events fire only on
            # state transitions. It deliberately reads nothing from and
            # writes nothing to threshold.py, so it cannot perturb the
            # cooldown/hysteresis state machine.
            reading_event = build_event(
                EventType.SENSOR_READING,
                message=f"{device_id} reported {message.get('co2')} ppm",
                severity=Severity.INFO,
                device_id=device_id,
                data={"co2": message.get("co2")},
            )
            await manager.broadcast(reading_event.to_dict())

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
    co2 = message.get("co2")
    sensor_timestamp = message.get("sensor_timestamp")

    try:
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
        logger.exception("Pipeline B (hash/DB) failed to process message: %r", message)
        error_event = build_event(
            EventType.DATABASE_ERROR,
            message=f"{device_id} Pipeline B failed: {exc}",
            severity=Severity.CRITICAL,
            device_id=device_id,
        )
        await manager.broadcast(error_event.to_dict())
        return  # nothing to anchor on-chain without a hash and a stored record

    # Blockchain anchoring gets its own try/except so a chain-side failure
    # (e.g. RPC down, wallet not funded) is reported as BLOCKCHAIN_FAILED
    # rather than clobbering the DATABASE_STORED success that already
    # happened above.
    try:
        submitted_event = build_event(
            EventType.BLOCKCHAIN_SUBMITTED,
            message=f"{device_id} hash submitted to Sepolia",
            severity=Severity.INFO,
            device_id=device_id,
        )
        await manager.broadcast(submitted_event.to_dict())

        tx_result = await blockchain_client.store_hash(hash_value)
        await update_blockchain_info(record_id, tx_result["tx_hash"], tx_result["record_id"])

        confirmed_event = build_event(
            EventType.BLOCKCHAIN_CONFIRMED,
            message=(
                f"{device_id} hash anchored on-chain: tx {tx_result['tx_hash']}, "
                f"record #{tx_result['record_id']}, block {tx_result['block_number']}"
            ),
            severity=Severity.INFO,
            device_id=device_id,
        )
        await manager.broadcast(confirmed_event.to_dict())
    except Exception as exc:
        logger.exception("Pipeline B (blockchain) failed to process message: %r", message)
        failed_event = build_event(
            EventType.BLOCKCHAIN_FAILED,
            message=f"{device_id} blockchain submission failed: {exc}",
            severity=Severity.CRITICAL,
            device_id=device_id,
        )
        await manager.broadcast(failed_event.to_dict())


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
    blockchain_client.start()  # tolerant of a not-yet-configured wallet/contract - see blockchain.py
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

# The React dashboard is served by Vite's dev server on a different port
# (5173 by default), so the browser treats its fetch() calls to this
# gateway as cross-origin and blocks them without these headers. The regex
# matches any localhost port because Vite picks the next free one if 5173
# is taken. WebSocket connections are not subject to CORS, so /ws works
# with or without this - only the REST endpoints need it.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "mqtt_broker": f"{settings.mqtt_broker_host}:{settings.mqtt_broker_port}",
        "mqtt_topic": settings.mqtt_topic,
        # Published so the dashboard's gauge and chart reference lines use
        # the gateway's actual configured thresholds rather than hardcoding
        # a second copy of them in JavaScript that could drift from .env.
        "co2_warning_threshold": settings.co2_warning_threshold,
        "co2_critical_threshold": settings.co2_critical_threshold,
    }


@app.get("/devices/status")
def devices_status() -> list[dict]:
    return device_status_tracker.snapshot()


@app.get("/records")
async def records(limit: int = Query(DEFAULT_RECORDS_LIMIT, ge=1, le=MAX_RECORDS_LIMIT)) -> list[dict]:
    """Recent readings, newest first. Backs both the Verification page
    (pick a record to verify) and Blockchain Logs (anchoring status per
    record) - the two need the same rows, so they share one endpoint."""
    return await get_recent_records(limit)


@app.get("/records/stats")
async def records_stats() -> dict:
    """Total readings stored and how many are anchored on-chain, for the
    Overview page's counts. Declared before nothing else claims /records/*,
    and kept separate from GET /records so a glance view never pays for
    transferring rows it won't display."""
    return await count_records()


@app.post("/verify/{record_id}")
async def verify(record_id: str) -> dict:
    return await verify_record(record_id)


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
