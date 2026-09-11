# Project: Blockchain-Based IoT Carbon Emission Monitoring System

## What this is
Final-year engineering capstone. A working demonstrable prototype (not production-grade)
proving two things: (1) real-time CO2 threshold alerting, and (2) blockchain-anchored
tamper-evident data integrity. Four layers: ESP32+MQ135 sensing, FastAPI gateway,
Ethereum Sepolia, React dashboard.

## Non-negotiable architecture decisions (do not silently change these)
- TWO INDEPENDENT PIPELINES from the same MQTT message:
  Pipeline A (fast): threshold check -> WebSocket alert. Must never wait on Mongo/hashing/blockchain.
  Pipeline B (background): SHA-256 -> MongoDB -> Sepolia. Runs as a separate asyncio task.
- paho-mqtt is SYNCHRONOUS. FastAPI/WebSocket is ASYNC. Bridge via a background thread
  (`loop_start()`) handing messages to asyncio via `asyncio.run_coroutine_threadsafe()`
  or an `asyncio.Queue`. Never call MQTT callbacks with raw `await`.
- Canonical hash fields: `device_id + co2 + sensor_timestamp` ONLY. `gateway_received_timestamp`
  is stored separately for latency display and is NOT part of the hash.
- Smart contract: `bytes32` hash (not string), auto-incrementing `uint recordId`, emits
  `HashStored` event. Only `storeHash()` and `getHash()`. NO on-chain verifyHash() -
  comparison happens in Python's verification.py.
- Backend wallet (private key from .env) signs transactions directly via Web3.py.
  MetaMask is only used for contract deployment and funding the test wallet -
  never assume MetaMask is in the runtime transaction path.
- Nonce handling: fetch once at startup, increment locally under a lock. Don't refetch
  from the node per transaction.
- Alert lifecycle: ACTIVE -> RESOLVED only (no manual acknowledgement step). Cooldown/
  hysteresis so alerts don't spam near the threshold boundary.
- Tampered records stay flagged permanently - no "resolve" state for tampering.
- ESP32 stays lightweight: sensor read -> ADC -> CO2 estimate -> JSON -> MQTT publish.
  Nothing else runs on the device.
- Keep failure handling minimal: try/except + a logged event. No retry frameworks,
  no circuit breakers, no message queues.
- Do NOT introduce microservices, Kubernetes, Kafka, Redis, or ML - still explicitly
  out of scope for this project. (Auth was on this list too, until Phase 5 below.)

## Phase 5: RBAC / auth (approved scope addition)
Originally this file excluded "auth systems" entirely. That was overridden deliberately
for Phase 5 - a users/regions/factories layer so a regional_head can see only their own
region's data while an admin sees everything. Everything else in this file still holds;
this section only adds to it, and does not touch Pipeline A/B, hashing, or the blockchain
flow in any way.
- JWT auth, stateless: `get_current_user` decodes/validates the token only - it does not
  re-read the user from MongoDB on every request. 8h expiry, no refresh tokens, by design
  (matches "keep failure handling minimal" - one fewer moving part). Consequence:
  deactivating a user or changing their role takes effect on their next login, not
  mid-session - accepted, not an oversight.
- Two roles only, no hierarchy: `admin` (region_id null, sees everything) and
  `regional_head` (region_id set, scoped to it). `require_role()` is a plain equality
  check. `region_scope_filter(current_user)` is the one place that turns a role into a
  Mongo filter - every region-scoped route should call it rather than reimplementing the
  admin-sees-all / regional_head-sees-own-region rule.
- `factory_id` on `sensor_data` is additive metadata only. It is NEVER part of the hash -
  the canonical hash fields (`device_id + co2 + sensor_timestamp`) are unchanged, and
  nothing in hashing.py, blockchain.py, or verification.py was touched to add it.
- First admin account is bootstrapped out-of-band via `Gateway/create_admin.py` (there is
  no open registration endpoint - by design, matching "no auth systems" being a deliberate,
  narrow exception rather than a green light for a full user-management surface).
- Schema/index changes (the `users`/`regions`/`factories` collections, the unique indexes
  on `users.username`/`users.email`, and the `sensor_data` `{device_id, sensor_timestamp}`
  compound index) are applied via the one-off `Gateway/migrate_schema.py`, not at gateway
  startup - keeps this fully decoupled from Pipeline A/B's hot path.

## Folder structure
CarbonEmissionProject/
    ESP32/              (main.ino, config.h)
    Gateway/             (FastAPI: app.py, mqtt_client.py, threshold.py, device_status.py,
                          events.py, websocket_manager.py, hashing.py, database.py,
                          blockchain.py, verification.py, scheduler.py, models.py, config.py,
                          auth.py, create_admin.py, migrate_schema.py)
    Dashboard/           (React: Overview, RealTimeData, Verification, BlockchainLogs, SystemMonitor)
    contracts/           (CarbonMonitor.sol)
    database/
    docs/
    tests/               (mqtt_test_publisher.py with --scenario normal|warning|critical|offline)

## Tech stack
Python 3.12, FastAPI, uvicorn, paho-mqtt, motor (async MongoDB), web3.py, apscheduler,
websockets, python-dotenv, pydantic, PyJWT, bcrypt. React + Vite, axios, recharts.
Solidity ^0.8.x on Sepolia testnet.

## Working style
- Explain what you're about to build and why before writing code.
- Build incrementally, one module at a time - don't generate the whole gateway in one shot.
- Give me exact commands to run and test each piece before moving to the next.
- If something in this file conflicts with a request I make, flag it rather than
  silently overriding the architecture.