"""
Tests for Gateway/config.py's env var loading and validation.

These write real, throwaway .env files via tempfile (a portable stand-in for
Gateway/.env) instead of relying on shell commands, so the tests behave the
same on Windows, macOS, and Linux and can be rerun any time with `pytest`.
"""

from pathlib import Path

import pytest
from dotenv import load_dotenv

import config

REQUIRED_VARS = [
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
OPTIONAL_VARS = ["GATEWAY_HOST", "GATEWAY_PORT", "LOG_LEVEL"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """
    Remove every config-related env var before each test. monkeypatch
    remembers the pre-test value (or absence) of each key it touches here,
    so even though the test itself loads new values straight into
    os.environ via dotenv (bypassing monkeypatch), teardown still restores
    exactly what was there before this test ran.
    """
    for name in REQUIRED_VARS + OPTIONAL_VARS:
        monkeypatch.delenv(name, raising=False)


def _write_env_file(tmp_path: Path, contents: str) -> Path:
    env_file = tmp_path / ".env"
    env_file.write_text(contents, encoding="utf-8")
    return env_file


def test_valid_env_loads_cleanly(tmp_path):
    env_file = _write_env_file(
        tmp_path,
        """
        MQTT_BROKER_HOST=test-broker.local
        MQTT_BROKER_PORT=1883
        MQTT_TOPIC=carbon/sensor01
        CO2_WARNING_THRESHOLD=800
        CO2_CRITICAL_THRESHOLD=1500
        CO2_HYSTERESIS_READINGS=2
        DEVICE_TIMEOUT_SECONDS=45
        MONGO_URI=mongodb://test-mongo:27017
        MONGO_DB_NAME=test_db
        SEPOLIA_RPC_URL=https://sepolia.infura.io/v3/test-project-id
        BLOCKCHAIN_PRIVATE_KEY=0x1111111111111111111111111111111111111111111111111111111111111111
        BLOCKCHAIN_ACCOUNT=0x2222222222222222222222222222222222222222
        CONTRACT_ADDRESS=0x3333333333333333333333333333333333333333
        """,
    )
    load_dotenv(env_file, override=True)

    result = config.load_config()

    assert result.mqtt_broker_host == "test-broker.local"
    assert result.mqtt_broker_port == 1883
    assert result.mqtt_topic == "carbon/sensor01"
    assert result.co2_warning_threshold == 800.0
    assert result.co2_critical_threshold == 1500.0
    assert result.co2_hysteresis_readings == 2
    assert result.device_timeout_seconds == 45
    assert result.mongo_uri == "mongodb://test-mongo:27017"
    assert result.mongo_db_name == "test_db"
    assert result.sepolia_rpc_url == "https://sepolia.infura.io/v3/test-project-id"
    assert result.blockchain_private_key == "0x1111111111111111111111111111111111111111111111111111111111111111"
    assert result.blockchain_account == "0x2222222222222222222222222222222222222222"
    assert result.contract_address == "0x3333333333333333333333333333333333333333"
    # Optional vars fall back to their defaults when not set.
    assert result.gateway_host == "0.0.0.0"
    assert result.gateway_port == 8000
    assert result.log_level == "INFO"

    # The private key must be readable via direct attribute access (the
    # app needs the real value to sign transactions)...
    assert result.blockchain_private_key == "0x1111111111111111111111111111111111111111111111111111111111111111"
    # ...but must never appear in repr()/str() of the Config object, so an
    # accidental print(settings) or a traceback holding the object can't
    # leak it.
    assert "1111111111111111111111111111111111111111111111111111111111111111" not in repr(result)
    assert "1111111111111111111111111111111111111111111111111111111111111111" not in str(result)
    assert "blockchain_private_key" not in repr(result)


def test_invalid_env_raises_combined_error(tmp_path):
    env_file = _write_env_file(
        tmp_path,
        """
        MQTT_BROKER_HOST=test-broker.local
        MQTT_BROKER_PORT=not_a_number
        MQTT_TOPIC=carbon/sensor01
        CO2_WARNING_THRESHOLD=2000
        CO2_CRITICAL_THRESHOLD=1000
        CO2_HYSTERESIS_READINGS=3
        """,
        # DEVICE_TIMEOUT_SECONDS is deliberately omitted to also cover the
        # "required but not set" branch in the same failing run.
    )
    load_dotenv(env_file, override=True)

    with pytest.raises(config.ConfigError) as exc_info:
        config.load_config()

    message = str(exc_info.value)
    assert "MQTT_BROKER_PORT must be an integer" in message
    assert "CO2_CRITICAL_THRESHOLD" in message and "must be greater than" in message
    assert "DEVICE_TIMEOUT_SECONDS is required but not set" in message


def test_malformed_blockchain_fields_are_rejected(tmp_path):
    env_file = _write_env_file(
        tmp_path,
        """
        MQTT_BROKER_HOST=test-broker.local
        MQTT_BROKER_PORT=1883
        MQTT_TOPIC=carbon/sensor01
        CO2_WARNING_THRESHOLD=800
        CO2_CRITICAL_THRESHOLD=1500
        CO2_HYSTERESIS_READINGS=2
        DEVICE_TIMEOUT_SECONDS=45
        MONGO_URI=mongodb://test-mongo:27017
        MONGO_DB_NAME=test_db
        SEPOLIA_RPC_URL=not-a-url
        BLOCKCHAIN_PRIVATE_KEY=too-short
        BLOCKCHAIN_ACCOUNT=not-an-address
        CONTRACT_ADDRESS=0xzz1111111111111111111111111111111111111
        """,
    )
    load_dotenv(env_file, override=True)

    with pytest.raises(config.ConfigError) as exc_info:
        config.load_config()

    message = str(exc_info.value)
    assert "SEPOLIA_RPC_URL must start with http:// or https://" in message
    assert "BLOCKCHAIN_PRIVATE_KEY must be a 64-hex-char private key" in message
    # The private key's actual (malformed) value must never be echoed into the error.
    assert "too-short" not in message
    assert "BLOCKCHAIN_ACCOUNT must be a 0x-prefixed 40-hex-char Ethereum address" in message
    assert "CONTRACT_ADDRESS must be a 0x-prefixed 40-hex-char Ethereum address" in message
