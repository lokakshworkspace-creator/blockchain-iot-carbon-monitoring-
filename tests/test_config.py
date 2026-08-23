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
    # Optional vars fall back to their defaults when not set.
    assert result.gateway_host == "0.0.0.0"
    assert result.gateway_port == 8000
    assert result.log_level == "INFO"


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
