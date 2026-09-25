"""Deactivate expired API keys on a schedule.

Validation already rejects a key past `expires_at`; this sweep makes `is_active` follow,
so `active_only` listings drop expired keys and the API-key update trigger records
`api_key_expired`. Every API process runs it: `sp_cleanup_expired_api_keys` only
matches keys that are still active, so concurrent replicas deactivate (and log) each
key once.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable

from src.Util.db import db_api_keys


logger = logging.getLogger(__name__)

API_KEY_EXPIRY_SWEEP_INTERVAL_SECONDS = 300


async def sweep_expired_api_keys(cleanup: Callable[[], int | None] | None = None) -> int | None:
    """Run one sweep. Never raises, so a database outage cannot end the loop."""

    try:
        deactivated = await asyncio.to_thread(cleanup or db_api_keys.cleanup_expired_keys)
    except Exception as exc:  # noqa: BLE001
        logger.warning("API key expiry sweep failed: %s", type(exc).__name__)
        return None
    if deactivated:
        logger.info("API key expiry sweep deactivated %s key(s)", deactivated)
    return deactivated


async def run_api_key_expiry_sweeper(interval_seconds: int = API_KEY_EXPIRY_SWEEP_INTERVAL_SECONDS) -> None:
    """Sweep every `interval_seconds` until cancelled by the application lifespan."""

    while True:
        await asyncio.sleep(interval_seconds)
        await sweep_expired_api_keys()
