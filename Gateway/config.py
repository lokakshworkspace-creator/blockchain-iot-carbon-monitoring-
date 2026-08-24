"""
Gateway configuration: loads and validates all environment variables the gateway
needs, and fails loudly (with every problem listed at once) if anything required
is missing or malformed. Nothing else in this codebase should call os.environ /
os.getenv directly - import `config` from here instead.

Phase 1 defined the variables needed for MQTT ingestion, threshold alerting,
and device-status tracking. Phase 2 adds MongoDB settings (MONGO_URI,
MONGO_DB_NAME) and the Sepolia/Web3 settings (SEPOLIA_RPC_URL,
BLOCKCHAIN_PRIVATE_KEY, BLOCKCHAIN_ACCOUNT, CONTRACT_ADDRESS) that
blockchain.py will use once it's built. VERIFICATION_INTERVAL_MINUTES
(optional, defaults to 10) controls scheduler.py's periodic tamper-check
cycle - kept deliberately optional with a conservative default rather
than required, since a missing value should fall back to something safe
rather than block gateway startup entirely.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load Gateway/.env explicitly (not the caller's cwd) so behavior is the same
# whether the app is started from the repo root or from inside Gateway/.
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=_ENV_PATH)


class ConfigError(RuntimeError):
    """Raised at startup when required configuration is missing or invalid."""


@dataclass(frozen=True)
class Config:
    # --- MQTT ---
    mqtt_broker_host: str
    mqtt_broker_port: int
    mqtt_topic: str

    # --- Threshold engine ---
    co2_warning_threshold: float
    co2_critical_threshold: float
    co2_hysteresis_readings: int

    # --- Device status tracking ---
    device_timeout_seconds: int

    # --- MongoDB (Pipeline B) ---
    mongo_uri: str
    mongo_db_name: str

    # --- Sepolia / Web3 (Pipeline B: blockchain anchoring) ---
    sepolia_rpc_url: str
    # repr=False so this never appears in a repr(config.settings)/str(...) -
    # e.g. an accidental print(settings) or a traceback that includes the
    # Config object would otherwise leak the backend wallet's private key.
    blockchain_private_key: str = field(repr=False)
    blockchain_account: str
    contract_address: str

    # --- Gateway HTTP/WebSocket server ---
    gateway_host: str
    gateway_port: int
    log_level: str

    # --- Periodic tamper-check scheduler (scheduler.py) ---
    verification_interval_minutes: int


def _require(raw: dict[str, str | None], errors: list[str], name: str) -> str | None:
    value = raw.get(name)
    if value is None or value.strip() == "":
        errors.append(f"  - {name} is required but not set")
        return None
    return value


def _as_int(errors: list[str], name: str, value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        errors.append(f"  - {name} must be an integer, got {value!r}")
        return None


def _as_float(errors: list[str], name: str, value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        errors.append(f"  - {name} must be a number, got {value!r}")
        return None


_ETH_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_PRIVATE_KEY_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")


def _as_eth_address(errors: list[str], name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not _ETH_ADDRESS_RE.match(value):
        errors.append(f"  - {name} must be a 0x-prefixed 40-hex-char Ethereum address, got {value!r}")
        return None
    return value


def _as_private_key(errors: list[str], name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if not _PRIVATE_KEY_RE.match(value):
        errors.append(f"  - {name} must be a 64-hex-char private key (with or without a 0x prefix)")
        return None
    return value


def load_config() -> Config:
    """
    Read and validate all required environment variables in one pass, raising a
    single ConfigError listing every problem found (instead of failing on the
    first one) so a developer can fix everything in one go.
    """
    required_names = [
        "MQTT_BROKER_HOST",
        "MQTT_BROKER_PORT",
        "MQTT_TOPIC",
        "CO2_WARNING_THRESHOLD",
        "CO2_CRITICAL_THRESHOLD",
        "CO2_HYSTERESIS_READINGS",
        "DEVICE_TIMEOUT_SECONDS",
        "MONGO_URI",
        "MONGO_DB_NAME",
        "SEPOLIA_RPC_URL",
        "BLOCKCHAIN_PRIVATE_KEY",
        "BLOCKCHAIN_ACCOUNT",
        "CONTRACT_ADDRESS",
    ]
    raw = {name: os.getenv(name) for name in required_names}

    errors: list[str] = []
    for name in required_names:
        _require(raw, errors, name)

    mqtt_broker_port = _as_int(errors, "MQTT_BROKER_PORT", raw["MQTT_BROKER_PORT"])
    co2_warning_threshold = _as_float(errors, "CO2_WARNING_THRESHOLD", raw["CO2_WARNING_THRESHOLD"])
    co2_critical_threshold = _as_float(errors, "CO2_CRITICAL_THRESHOLD", raw["CO2_CRITICAL_THRESHOLD"])
    co2_hysteresis_readings = _as_int(errors, "CO2_HYSTERESIS_READINGS", raw["CO2_HYSTERESIS_READINGS"])
    device_timeout_seconds = _as_int(errors, "DEVICE_TIMEOUT_SECONDS", raw["DEVICE_TIMEOUT_SECONDS"])

    sepolia_rpc_url = raw["SEPOLIA_RPC_URL"]
    if sepolia_rpc_url is not None and not sepolia_rpc_url.startswith(("http://", "https://")):
        errors.append(f"  - SEPOLIA_RPC_URL must start with http:// or https://, got {sepolia_rpc_url!r}")

    blockchain_private_key = _as_private_key(errors, "BLOCKCHAIN_PRIVATE_KEY", raw["BLOCKCHAIN_PRIVATE_KEY"])
    blockchain_account = _as_eth_address(errors, "BLOCKCHAIN_ACCOUNT", raw["BLOCKCHAIN_ACCOUNT"])
    contract_address = _as_eth_address(errors, "CONTRACT_ADDRESS", raw["CONTRACT_ADDRESS"])

    if (
        co2_warning_threshold is not None
        and co2_critical_threshold is not None
        and co2_critical_threshold <= co2_warning_threshold
    ):
        errors.append(
            "  - CO2_CRITICAL_THRESHOLD "
            f"({co2_critical_threshold}) must be greater than CO2_WARNING_THRESHOLD "
            f"({co2_warning_threshold})"
        )

    if co2_hysteresis_readings is not None and co2_hysteresis_readings < 1:
        errors.append("  - CO2_HYSTERESIS_READINGS must be >= 1")

    if device_timeout_seconds is not None and device_timeout_seconds <= 0:
        errors.append("  - DEVICE_TIMEOUT_SECONDS must be > 0")

    # Optional, with defaults - never fatal.
    gateway_host = os.getenv("GATEWAY_HOST", "0.0.0.0")
    gateway_port_raw = os.getenv("GATEWAY_PORT", "8000")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    verification_interval_minutes_raw = os.getenv("VERIFICATION_INTERVAL_MINUTES", "10")

    gateway_port = _as_int(errors, "GATEWAY_PORT", gateway_port_raw)
    verification_interval_minutes = _as_int(
        errors, "VERIFICATION_INTERVAL_MINUTES", verification_interval_minutes_raw
    )
    if verification_interval_minutes is not None and verification_interval_minutes <= 0:
        errors.append("  - VERIFICATION_INTERVAL_MINUTES must be > 0")

    if errors:
        env_file_note = (
            f"(looked for {_ENV_PATH})" if _ENV_PATH.exists() else f"(no .env file found at {_ENV_PATH})"
        )
        raise ConfigError(
            "Gateway configuration is invalid " + env_file_note + ":\n"
            + "\n".join(errors)
            + "\n\nCopy Gateway/.env.example to Gateway/.env and fill in the missing values."
        )

    assert mqtt_broker_port is not None
    assert co2_warning_threshold is not None
    assert co2_critical_threshold is not None
    assert co2_hysteresis_readings is not None
    assert device_timeout_seconds is not None
    assert gateway_port is not None
    assert verification_interval_minutes is not None
    assert sepolia_rpc_url is not None
    assert blockchain_private_key is not None
    assert blockchain_account is not None
    assert contract_address is not None

    return Config(
        mqtt_broker_host=raw["MQTT_BROKER_HOST"],  # type: ignore[arg-type]
        mqtt_broker_port=mqtt_broker_port,
        mqtt_topic=raw["MQTT_TOPIC"],  # type: ignore[arg-type]
        co2_warning_threshold=co2_warning_threshold,
        co2_critical_threshold=co2_critical_threshold,
        co2_hysteresis_readings=co2_hysteresis_readings,
        device_timeout_seconds=device_timeout_seconds,
        mongo_uri=raw["MONGO_URI"],  # type: ignore[arg-type]
        mongo_db_name=raw["MONGO_DB_NAME"],  # type: ignore[arg-type]
        sepolia_rpc_url=sepolia_rpc_url,
        blockchain_private_key=blockchain_private_key,
        blockchain_account=blockchain_account,
        contract_address=contract_address,
        gateway_host=gateway_host,
        gateway_port=gateway_port,
        log_level=log_level,
        verification_interval_minutes=verification_interval_minutes,
    )


# Loaded once at import time so the app fails immediately on startup if
# configuration is bad, rather than on the first request.
settings = load_config()
