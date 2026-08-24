"""
Tests for Gateway/blockchain.py's BlockchainClient, using plain fake
stand-ins for Web3/contract/account (no real network calls, no funded
wallet needed) - matching the FakeMQTTMessage style used for
mqtt_client.py's tests. Exercises: not-ready guard, bad-hash-length
rejection (must not consume a nonce), receipt/event parsing, that
concurrent calls get sequential, non-duplicate nonces despite each one
running in its own worker thread via asyncio.to_thread(), and - added
after a Phase 4 soak test caught a live nonce-leak bug - that a nonce is
only ever consumed once send_raw_transaction has actually succeeded,
never for a failure before or during submission.
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
        self._gas_price = 1_000_000_000
        self.chain_id = 11155111
        self.sent_nonces: list[int] = []
        # When set, the next send_raw_transaction call raises this instead
        # of succeeding - stands in for an RPC-level failure (rate limit,
        # network error) that happens before the node ever sees the
        # transaction. Cleared after raising once, so a later retry with
        # the same fake client can succeed.
        self.send_raw_transaction_error: Exception | None = None
        # Same idea, but for a failure even earlier - fetching the gas
        # price, before build_transaction has even assembled a tx to sign.
        self.gas_price_error: Exception | None = None

    @property
    def gas_price(self) -> int:
        if self.gas_price_error is not None:
            error, self.gas_price_error = self.gas_price_error, None
            raise error
        return self._gas_price

    def send_raw_transaction(self, raw_transaction) -> _FakeTxHash:
        if self.send_raw_transaction_error is not None:
            error, self.send_raw_transaction_error = self.send_raw_transaction_error, None
            raise error
        self.sent_nonces.append(raw_transaction["nonce"])
        return _FakeTxHash(b"\x11" * 32)

    def wait_for_transaction_receipt(self, tx_hash, timeout=120) -> dict:
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


def test_store_hash_does_not_consume_a_nonce_when_send_raw_transaction_fails():
    # A Phase 4 soak test proved this matters live: Alchemy's rate limit
    # (HTTP 429) can reject send_raw_transaction itself, meaning the node
    # never saw the transaction at all. If the nonce had already advanced
    # for that attempt, it would be permanently skipped - and since
    # Ethereum requires strictly sequential nonces per account, every
    # later transaction from this wallet would be stuck behind the gap
    # until the process restarted and refetched the real on-chain nonce.
    client = _make_ready_client(starting_nonce=5)
    client._w3.eth.send_raw_transaction_error = RuntimeError("simulated 429 Too Many Requests")

    with pytest.raises(RuntimeError, match="429"):
        asyncio.run(client.store_hash(SAMPLE_HASH))

    assert client._nonce == 5  # the failed attempt must not have burned nonce 5

    # The very next attempt must reuse the same nonce, not skip to 6.
    result = asyncio.run(client.store_hash(SAMPLE_HASH))
    assert client._w3.eth.sent_nonces == [5]
    assert client._nonce == 6
    assert result["tx_hash"] == "0x" + ("11" * 32)


def test_store_hash_does_not_consume_a_nonce_when_gas_price_fetch_fails():
    # Same principle, but for a failure even earlier in the sequence -
    # before build_transaction has even assembled a transaction to sign,
    # let alone reached send_raw_transaction.
    client = _make_ready_client(starting_nonce=5)
    client._w3.eth.gas_price_error = RuntimeError("simulated RPC connection error")

    with pytest.raises(RuntimeError, match="connection error"):
        asyncio.run(client.store_hash(SAMPLE_HASH))

    assert client._nonce == 5

    asyncio.run(client.store_hash(SAMPLE_HASH))
    assert client._w3.eth.sent_nonces == [5]
    assert client._nonce == 6


def test_store_hash_keeps_the_nonce_consumed_when_only_the_receipt_wait_fails():
    # The opposite case: once send_raw_transaction has succeeded, the
    # transaction is genuinely on-chain regardless of what happens next.
    # A failure here (timeout, RPC error while polling for the receipt)
    # must NOT roll back the nonce - doing so would let a later call reuse
    # a nonce that a real, already-broadcast transaction is using,
    # producing a genuine on-chain collision instead of just a
    # BLOCKCHAIN_FAILED report.
    client = _make_ready_client(starting_nonce=5)

    def _raise_timeout(tx_hash, timeout=120):
        raise TimeoutError("simulated: not in the chain after 300 seconds")

    client._w3.eth.wait_for_transaction_receipt = _raise_timeout

    with pytest.raises(TimeoutError, match="300 seconds"):
        asyncio.run(client.store_hash(SAMPLE_HASH))

    # The transaction WAS sent (nonce 5) even though we never got its
    # receipt, so the nonce must already reflect that.
    assert client._w3.eth.sent_nonces == [5]
    assert client._nonce == 6


def test_concurrent_store_hash_calls_get_sequential_unique_nonces():
    client = _make_ready_client(starting_nonce=5)

    async def _run():
        await asyncio.gather(*[client.store_hash(SAMPLE_HASH) for _ in range(5)])

    asyncio.run(_run())

    used_nonces = client._w3.eth.sent_nonces
    assert sorted(used_nonces) == [5, 6, 7, 8, 9]
    assert len(set(used_nonces)) == 5  # no nonce reused across concurrent calls
    assert client._nonce == 10
