"""Expired API keys are deactivated, and the unwritten activity types now have writers.

Regression: `cleanup_expired_keys` (`sp_cleanup_expired_api_keys`) had no caller, so
expired keys kept `is_active=true` and `active_only` listings returned them; and
`api_key_expired`, `email_message_enqueued` and `email_message_dead_lettered` were
seeded in the activity catalog but written by nothing.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI

from src.Util import api_key_expiry


ROOT = Path(__file__).resolve().parents[2]


def _sql(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _trigger_body(sql: str, name: str) -> str:
    match = re.search(rf"CREATE TRIGGER {name}\b(.*?)END//", sql, re.S)
    assert match, name
    return match.group(1)


def test_sweep_runs_the_cleanup_procedure_wrapper():
    with patch("src.Util.db.db_api_keys.cleanup_expired_keys", return_value=3) as cleanup:
        assert asyncio.run(api_key_expiry.sweep_expired_api_keys()) == 3
    cleanup.assert_called_once_with()


def test_sweep_survives_a_database_failure():
    with patch("src.Util.db.db_api_keys.cleanup_expired_keys", side_effect=RuntimeError("db down")):
        assert asyncio.run(api_key_expiry.sweep_expired_api_keys()) is None


def test_sweeper_repeats_until_cancelled():
    calls = MagicMock(return_value=0)

    async def scenario():
        with patch("src.Util.db.db_api_keys.cleanup_expired_keys", calls):
            task = asyncio.create_task(api_key_expiry.run_api_key_expiry_sweeper(interval_seconds=0))
            while calls.call_count < 2:
                await asyncio.sleep(0.01)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    asyncio.run(asyncio.wait_for(scenario(), timeout=5))
    assert calls.call_count >= 2


def test_app_lifespan_starts_and_stops_the_sweeper():
    import src.main as main

    state = {"started": False, "cancelled": False}

    async def fake_sweeper():
        state["started"] = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    async def scenario():
        with patch.object(main, "run_api_key_expiry_sweeper", fake_sweeper), patch.object(
            main.assistant, "shutdown_assistant", AsyncMock()
        ):
            async with main.lifespan(FastAPI()):
                await asyncio.sleep(0)

    asyncio.run(scenario())
    assert state == {"started": True, "cancelled": True}


def test_api_key_update_trigger_records_expiry_without_revocation():
    body = _trigger_body(_sql("schemas/triggers/03_api_key_activity_triggers.sql"), "trg_after_api_key_update")
    expired = body[body.index("'api_key_expired'") - 600 : body.index("'api_key_expired'")]
    assert "NEW.is_active = FALSE AND OLD.is_active = TRUE AND NEW.revoked_at IS NULL" in expired
    assert "NEW.expires_at <= NOW()" in expired


def test_outbox_triggers_record_enqueue_and_dead_letter_without_recipients():
    sql = _sql("schemas/triggers/04_email_activation_triggers.sql")
    inserted = _trigger_body(sql, "trg_email_messages_after_insert")
    updated = _trigger_body(sql, "trg_email_messages_after_update")
    assert "AFTER INSERT ON email_messages" in inserted and "'email_message_enqueued'" in inserted
    assert "AFTER UPDATE ON email_messages" in updated and "'email_message_dead_lettered'" in updated
    assert "NEW.status = 'dead' AND OLD.status <> 'dead'" in updated
    assert "recipient" not in (inserted + updated).lower()


def test_schema_sync_reapplies_both_trigger_files():
    patch_files = re.search(r"PATCH_FILES = \((.*?)\n\)", _sql("scripts/schema_sync.py"), re.S).group(1)
    assert '"triggers/03_api_key_activity_triggers.sql"' in patch_files
    assert '"triggers/04_email_activation_triggers.sql"' in patch_files
