"""Tests for Gateway/hashing.py's canonical SHA-256 hash generation."""

import re

from hashing import generate_hash

HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


def test_same_input_produces_same_hash():
    a = generate_hash("esp32-01", 850.5, "2026-08-23T00:00:00+00:00")
    b = generate_hash("esp32-01", 850.5, "2026-08-23T00:00:00+00:00")
    assert a == b


def test_different_device_id_produces_different_hash():
    a = generate_hash("esp32-01", 850.5, "2026-08-23T00:00:00+00:00")
    b = generate_hash("esp32-02", 850.5, "2026-08-23T00:00:00+00:00")
    assert a != b


def test_different_co2_produces_different_hash():
    a = generate_hash("esp32-01", 850.5, "2026-08-23T00:00:00+00:00")
    b = generate_hash("esp32-01", 850.6, "2026-08-23T00:00:00+00:00")
    assert a != b


def test_different_timestamp_produces_different_hash():
    a = generate_hash("esp32-01", 850.5, "2026-08-23T00:00:00+00:00")
    b = generate_hash("esp32-01", 850.5, "2026-08-23T00:00:01+00:00")
    assert a != b


def test_output_is_64_lowercase_hex_chars():
    result = generate_hash("esp32-01", 850.5, "2026-08-23T00:00:00+00:00")
    assert HEX64_RE.match(result), f"expected 64 lowercase hex chars, got {result!r}"


def test_int_and_float_co2_of_equal_value_hash_identically():
    # A real device's JSON might send a whole-number co2 as an int (700) or
    # a float (700.0) depending on formatting - both must hash the same way
    # since they represent the same reading.
    as_int = generate_hash("esp32-01", 700, "2026-08-23T00:00:00+00:00")
    as_float = generate_hash("esp32-01", 700.0, "2026-08-23T00:00:00+00:00")
    assert as_int == as_float
