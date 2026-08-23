# Blockchain-Based IoT CO2 Emission Monitoring System

Final-year engineering capstone prototype demonstrating:
1. **Real-time CO2 threshold alerting** — sensor data streamed over MQTT, evaluated
   against WARNING/CRITICAL thresholds, and pushed to a live dashboard over WebSocket.
2. **Blockchain-anchored tamper-evident data integrity** — every reading is hashed
   (SHA-256), stored in MongoDB, and anchored on Ethereum Sepolia so tampering with
   historical data can be detected.

Four layers: ESP32 + MQ135 sensing -> FastAPI gateway -> Ethereum Sepolia -> React dashboard.

## Architecture at a glance

Every MQTT message from a sensor triggers **two independent pipelines**:

- **Pipeline A (fast, synchronous path)**: threshold check -> WebSocket alert.
  Never blocked by hashing, database writes, or blockchain calls.
- **Pipeline B (background)**: SHA-256 hash -> MongoDB write -> Sepolia transaction.
  Runs as a separate asyncio task and never delays Pipeline A.

See [CLAUDE.md](./CLAUDE.md) for the full set of non-negotiable architecture decisions
(MQTT/asyncio bridging, canonical hash fields, smart contract shape, nonce handling,
alert lifecycle, etc.) — consult it before changing any core design choice.

## Folder structure

```
ESP32/          Arduino firmware (main.ino, config.h) - sensor read -> MQTT publish only
Gateway/        FastAPI backend - MQTT bridge, threshold engine, WebSocket alerts,
                hashing, MongoDB, blockchain integration
Dashboard/      React + Vite frontend (Overview, RealTimeData, Verification,
                BlockchainLogs, SystemMonitor)
contracts/      Solidity smart contract (CarbonMonitor.sol)
database/       MongoDB-related assets/scripts
docs/           Project documentation
tests/          Test utilities, incl. mqtt_test_publisher.py for simulating ESP32 data
```

## Project status

**Phase 1 (in progress):** Foundation & real-time alert pipeline, fully simulated —
no hardware, no database, no blockchain yet. MQTT -> threshold evaluation -> WebSocket
broadcast, backed by a simulated publisher script standing in for the ESP32.

Later phases (not started): MongoDB persistence + SHA-256 hashing (Pipeline B),
Sepolia smart contract integration, React dashboard, real ESP32 hardware.

## Requirements

- Python 3.12+
- A running MQTT broker (e.g. Mosquitto) on `localhost:1883` for local development
- Node.js (for the Dashboard, later phases)

## Gateway quick start

See [Gateway/README.md](./Gateway/README.md) (added alongside the Gateway code) for
setup and run instructions once Phase 1 development begins.
