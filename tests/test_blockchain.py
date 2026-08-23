"""
Tests for Gateway/blockchain.py's BlockchainClient, using plain fake
stand-ins for Web3/contract/account (no real network calls, no funded
wallet needed) - matching the FakeMQTTMessage style used for
mqtt_client.py's tests. Exercises: not-ready guard, bad-hash-length
rejection (must not consume a nonce), receipt/event parsing, and that
concurrent calls get sequential, non-duplicate nonces despite each one
running in its own worker thread via asyncio.to_thread().
"""

import asyncio

import pytest

import blockchain


class _FakeTxHash:
    """Stands in for the real HexBytes return value - only to_0x_hex() is
    used by blockchain.py, matching hexbytes 2.x (whose plain .hex() no
    longer auto-prefixes 0x, unlike older releases)."""

    def __init__(self, value: bytes) -> None:
        self._value = value

    def to_0x_hex(self) -> str:
        return "0x" + self._value.hex()


class _FakeEth:
    def __init__(self) -> None:
        self.gas_price = 1_000_000_000
        self.chain_id = 11155111
        self.sent_nonces: list[int] = []

    def send_raw_transaction(self, raw_transaction) -> _FakeTxHash:
        self.sent_nonces.append(raw_transaction["nonce"])
        return _FakeTxHash(b"\x11" * 32)

    def wait_for_transaction_receipt(self, tx_hash) -> dict:
        return {"blockNumber": 123, "status": 1}


class _FakeW3:
    def __init__(self) -> None:
        self.eth = _FakeEth()


class _FakeSignedTx:
    def __init__(self, raw_transaction: dict) -> None:
        self.raw_transaction = raw_transaction


class _FakeAccount:
    address = "0xFakeAccount0000000000000000000000000000"

    def sign_transaction(self, tx: dict) -> _FakeSignedTx:
        return _FakeSignedTx(tx)  # pass the whole tx through so tests can inspect its nonce


class _FakeStoreHashFunction:
    def __init__(self, hash_bytes: bytes) -> None:
        self.hash_bytes = hash_bytes

    def build_transaction(self, params: dict) -> dict:
        return dict(params)


class _FakeFunctions:
    def storeHash(self, hash_bytes: bytes) -> _FakeStoreHashFunction:
        return _FakeStoreHashFunction(hash_bytes)


class _FakeHashStoredEvent:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    def __call__(self):
        return self

    def process_receipt(self, receipt):
        return self._events


class _FakeEvents:
    def __init__(self, events: list[dict]) -> None:
        self.HashStored = _FakeHashStoredEvent(events)


class _FakeContract:
    def __init__(self, events: list[dict]) -> None:
        self.functions = _FakeFunctions()
        self.events = _FakeEvents(events)


def _make_ready_client(events: list[dict] | None = None, starting_nonce: int = 5) -> blockchain.BlockchainClient:
    client = blockchain.BlockchainClient()
    client._w3 = _FakeW3()
    client._contract = _FakeContract(events if events is not None else [{"args": {"recordId": 42}}])
    client._account = _FakeAccount()
    client._nonce = starting_nonce
    client._ready = True
    return client


SAMPLE_HASH = "a" * 64  # 64 hex chars = 32 bytes, a valid stand-in for a real SHA-256 hex digest


def test_store_hash_raises_when_client_never_started():
    client = blockchain.BlockchainClient()  # start() never called - not ready
    with pytest.raises(RuntimeError, match="not ready"):
        asyncio.run(client.store_hash(SAMPLE_HASH))


def test_store_hash_rejects_wrong_length_hash_without_consuming_a_nonce():
    client = _make_ready_client(starting_nonce=5)

    with pytest.raises(ValueError, match="32-byte"):
        asyncio.run(client.store_hash("deadbeef"))  # far too short

    assert client._nonce == 5  # a rejected input must not burn a nonce


def test_store_hash_returns_parsed_tx_and_event_info():
    client = _make_ready_client(events=[{"args": {"recordId": 42}}])

    result = asyncio.run(client.store_hash(SAMPLE_HASH))

    assert result["record_id"] == 42
    assert result["block_number"] == 123
    assert result["status"] == 1
    assert result["tx_hash"] == "0x" + ("11" * 32)


def test_store_hash_with_no_matching_event_returns_none_record_id():
    client = _make_ready_client(events=[])
    result = asyncio.run(client.store_hash(SAMPLE_HASH))
    assert result["record_id"] is None


def test_concurrent_store_hash_calls_get_sequential_unique_nonces():
    client = _make_ready_client(starting_nonce=5)

    async def _run():
        await asyncio.gather(*[client.store_hash(SAMPLE_HASH) for _ in range(5)])

    asyncio.run(_run())

    used_nonces = client._w3.eth.sent_nonces
    assert sorted(used_nonces) == [5, 6, 7, 8, 9]
    assert len(set(used_nonces)) == 5  # no nonce reused across concurrent calls
    assert client._nonce == 10
