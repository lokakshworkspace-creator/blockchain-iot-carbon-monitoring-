"""
Periodic tamper-check scheduler - the piece of CLAUDE.md's settled design
that catches tampering even if nobody happens to open Verification and
click Verify. Before this module, verification.py's verify_record() only
ran on-demand via POST /verify/{id}; nothing re-checked an anchored
record on its own.

This module owns WHEN and WHICH records to check. It never reimplements
verify_record()'s hash comparison - that logic already exists and is
already tested, so every scheduled check calls it directly and broadcasts
the exact same VERIFICATION_STARTED/VERIFICATION_SUCCESS/
VERIFICATION_FAILED/TAMPERING_DETECTED events a manual check does. The
dashboard cannot tell, and does not need to tell, which one triggered a
given event.

Kept deliberately conservative on RPC load, per Phase 4's soak-test
findings: a long interval (VERIFICATION_INTERVAL_MINUTES, default 10
minutes) and a small, fixed sample of the most-recently-anchored records
(RECHECK_SAMPLE_SIZE) - never the whole collection, every cycle. Calling
blockchain_client.get_hash() on every anchored record on a short
interval is exactly the kind of sustained blockchain-call volume that
produced Phase 4's rate-limiting and mempool-congestion findings.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import get_recently_anchored_records, mark_auto_verified
from verification import verify_record

logger = logging.getLogger(__name__)

# How many of the most-recently-anchored records to re-check per cycle.
# Small and fixed rather than configurable - see the module docstring on
# why "not the whole collection" is the entire point.
RECHECK_SAMPLE_SIZE = 5

_JOB_ID = "periodic_tamper_check"


async def run_verification_cycle() -> None:
    """One scheduled pass: re-verify a small sample of recently anchored
    records. Never raises - a single cycle failing to even fetch its
    sample must not stop future cycles from running (per CLAUDE.md's
    "minimal failure handling", the same standard every other background
    loop in this gateway follows)."""
    try:
        records = await get_recently_anchored_records(RECHECK_SAMPLE_SIZE)
    except Exception:
        logger.exception("Scheduled verification cycle could not fetch records to check")
        return

    logger.info("Scheduled verification cycle: checking %d record(s)", len(records))

    for record in records:
        record_id = record["id"]
        try:
            await verify_record(record_id)
            await mark_auto_verified(record_id)
        except Exception:
            # verify_record() already catches and reports its own
            # failures as VERIFICATION_FAILED; this only guards the
            # bookkeeping call and the loop itself, so one bad record
            # can't stop the rest of this cycle's sample.
            logger.exception("Scheduled verification failed unexpectedly for record %s", record_id)


class VerificationScheduler:
    """Thin wrapper around apscheduler's AsyncIOScheduler, matching the
    start()/stop() shape of mqtt_client.MQTTBridge and
    blockchain.BlockchainClient so app.py's lifespan can manage all three
    background services the same way."""

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        self._scheduler.add_job(
            run_verification_cycle,
            "interval",
            minutes=settings.verification_interval_minutes,
            id=_JOB_ID,
        )
        self._scheduler.start()
        logger.info(
            "Verification scheduler started: checking %d record(s) every %d minute(s)",
            RECHECK_SAMPLE_SIZE,
            settings.verification_interval_minutes,
        )

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)


scheduler = VerificationScheduler()
