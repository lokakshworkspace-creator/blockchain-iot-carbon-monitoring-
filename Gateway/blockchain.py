"""
Sends each Pipeline B hash to CarbonMonitor.sol on Sepolia via Web3.py,
signing locally with the backend wallet's private key (MetaMask is never
in this runtime path - it's only used for deployment/funding). web3.py's
HTTPProvider makes synchronous network calls, so every blockchain call
here runs inside asyncio.to_thread() rather than directly on the event
loop - the same reasoning as mqtt_client.py's background thread: a
multi-second RPC round trip must never stall Pipeline A or other Pipeline
B tasks sharing the event loop.

Nonce handling per CLAUDE.md: fetched once at startup from the chain, then
incremented locally under a lock for every transaction - never refetched
per call. Since to_thread() can run concurrent calls on different worker
threads, the lock has to be a real threading.Lock, not an asyncio.Lock
(which only makes sense on the event loop thread).
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

from eth_account import Account
from web3 import Web3

from config import settings

logger = logging.getLogger(__name__)

_ABI_PATH = Path(__file__).resolve().parent.parent / "contracts" / "CarbonMonitor.abi.json"


class BlockchainClient:
    def __init__(self) -> None:
        self._w3: Web3 | None = None
        self._contract: Any = None
        self._account: Any = None
        self._nonce: int | None = None
        self._nonce_lock = threading.Lock()
        self._ready = False

    def start(self) -> None:
        """Connect to Sepolia, load the contract, derive the backend
        wallet from its private key, and fetch the starting nonce. Must be
        called once at gateway startup, not per transaction.

        Tolerant of a not-yet-configured wallet/contract (e.g.
        BLOCKCHAIN_PRIVATE_KEY still a placeholder while waiting on
        deployment): logs a clear error and leaves the client not ready,
        rather than crashing the whole gateway's startup. store_hash()
        raises a clear error if called while not ready.
        """
        try:
            self._w3 = Web3(Web3.HTTPProvider(settings.sepolia_rpc_url))
            with _ABI_PATH.open(encoding="utf-8") as f:
                abi = json.load(f)
            contract_address = Web3.to_checksum_address(settings.contract_address)
            self._contract = self._w3.eth.contract(address=contract_address, abi=abi)
            self._account = Account.from_key(settings.blockchain_private_key)
            # "pending" (not the default "latest") so a restart never
            # collides with a transaction that's already broadcast but not
            # yet mined - "latest" would return a stale, already-used nonce.
            self._nonce = self._w3.eth.get_transaction_count(self._account.address, "pending")
            self._ready = True
            logger.info(
                "Blockchain client ready: account=%s contract=%s starting nonce=%s",
                self._account.address,
                contract_address,
                self._nonce,
            )
        except Exception:
            logger.exception(
                "Blockchain client failed to start (check SEPOLIA_RPC_URL / "
                "BLOCKCHAIN_PRIVATE_KEY / CONTRACT_ADDRESS) - Pipeline B's blockchain "
                "step will fail until this is fixed"
            )
            self._ready = False

    async def store_hash(self, hash_hex: str) -> dict:
        """Signs and sends one storeHash(hash) transaction, waits for its
        receipt, and returns {tx_hash, block_number, status, record_id}.
        record_id comes from decoding the HashStored event in the receipt,
        since a mined transaction's return value isn't otherwise readable.
        """
        if not self._ready:
            raise RuntimeError("Blockchain client is not ready (see startup logs)")
        return await asyncio.to_thread(self._store_hash_sync, hash_hex)

    def _store_hash_sync(self, hash_hex: str) -> dict:
        hash_bytes = bytes.fromhex(hash_hex)
        if len(hash_bytes) != 32:
            raise ValueError(f"expected a 32-byte (64-hex-char) hash, got {len(hash_bytes)} bytes")

        # The nonce must only advance once send_raw_transaction has
        # actually returned successfully - i.e. once the node has accepted
        # the transaction. A Phase 4 soak test proved this matters: under
        # RPC rate-limiting, gas_price/chain_id/send_raw_transaction can
        # all fail (network errors, 429s) *before* anything reaches the
        # node. If the nonce had already been advanced at that point (as
        # it was here previously), that nonce is burned forever - no
        # transaction ever used it, but Ethereum requires strictly
        # sequential nonces per account, so every later transaction from
        # this wallet would be stuck behind the gap. Holding the lock
        # across the whole build/sign/send sequence (not just the
        # increment) serializes that fast, sub-second commit step across
        # concurrent Pipeline B calls, which is what actually keeps nonce
        # assignment race-free; the slow, multi-minute receipt wait below
        # deliberately happens outside the lock so concurrent calls can
        # wait on their own confirmations in parallel.
        with self._nonce_lock:
            nonce = self._nonce
            tx = self._contract.functions.storeHash(hash_bytes).build_transaction(
                {
                    "from": self._account.address,
                    "nonce": nonce,
                    "gas": 200_000,  # generous fixed limit for a single SSTORE; no dynamic estimation needed
                    "gasPrice": self._w3.eth.gas_price,
                    "chainId": self._w3.eth.chain_id,
                }
            )
            signed = self._account.sign_transaction(tx)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            self._nonce += 1

        # Sepolia confirmation times observed in practice range well past
        # the 120s default (one took ~117s, another exceeded it outright) -
        # 300s gives real headroom without the call blocking forever. A
        # failure here (timeout, RPC error while polling) does NOT roll
        # back the nonce above: the transaction was genuinely broadcast,
        # so that nonce is correctly consumed on-chain regardless of
        # whether we ever observe its receipt.
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=300)

        events = self._contract.events.HashStored().process_receipt(receipt)
        record_id = events[0]["args"]["recordId"] if events else None

        return {
            # HexBytes.hex() does NOT include a 0x prefix in this version
            # (unlike older hexbytes releases) - to_0x_hex() gives the
            # canonical form, consistent with every other 0x-prefixed
            # value (addresses, contract_address) elsewhere in this codebase.
            "tx_hash": tx_hash.to_0x_hex(),
            "block_number": receipt["blockNumber"],
            "status": receipt["status"],
            "record_id": record_id,
        }

    async def get_hash(self, record_id: int) -> str:
        """Read-only call to CarbonMonitor.getHash(record_id) - no gas, no
        signing, no nonce involved. Returns whatever hex format the
        installed web3.py version's bytes.hex() produces; callers that
        compare this against another hash (verification.py) must normalize
        both sides rather than assume a particular 0x-prefix convention."""
        if not self._ready:
            raise RuntimeError("Blockchain client is not ready (see startup logs)")
        return await asyncio.to_thread(self._get_hash_sync, record_id)

    def _get_hash_sync(self, record_id: int) -> str:
        hash_bytes = self._contract.functions.getHash(record_id).call()
        return hash_bytes.hex()


client = BlockchainClient()
