"""The Patreon sync worker persists its activity through the real ``db_patreon`` module.

Regression: the worker looked up ``record_patreon_activity``, ``record_sync_retry``,
``mark_entitlement_stale``, ``record_provider_health`` and a DB heartbeat on
``db_patreon``, none of which existed, so ``act-cat-084``/``086``/``087``/``090`` were
never persisted and the token codes ``088``/``089`` were recorded nowhere. These tests
drive the worker against the real module with only the activity-log write patched.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.Util import activity_logger
from src.Util.db import db_patreon
from src.Util.patreon.client import PatreonUnauthorizedError


WORKER_SOURCE = Path(__file__).resolve().parents[2] / "src" / "workers" / "patreon_sync_worker.py"


def _config(**overrides):
    values = {"sync_enabled": True, "creator_token_refresh_enabled": False, "worker_poll_seconds": 1}
    values.update(overrides)
    return SimpleNamespace(**values)


def _worker(*, client=None, **config):
    from src.workers.patreon_sync_worker import PatreonSyncWorker

    return PatreonSyncWorker(worker_id="unit-worker", client=client, db_module=db_patreon, config=_config(**config))


def _written_types(log_activity: MagicMock) -> list[str]:
    return [call.kwargs["activity_type"] for call in log_activity.call_args_list]


def test_record_patreon_activity_writes_a_redacted_patreon_row():
    with patch.object(activity_logger.ActivityLogger, "log_activity", return_value=True) as log_activity:
        assert db_patreon.record_patreon_activity(
            event="patreon_sync_completed",
            outcome="completed",
            details={"pages_fetched": 2, "action": "ignored", "access_token": "secret-not-real"},
        )

    kwargs = log_activity.call_args.kwargs
    assert kwargs["activity_type"] == "patreon_sync_completed"
    assert kwargs["details"]["action"] == "patreon_sync_completed"
    assert kwargs["details"]["outcome"] == "completed"
    assert kwargs["details"]["pages_fetched"] == 2
    assert "secret-not-real" not in str(kwargs["details"])


def test_every_event_the_worker_emits_reaches_the_activity_log():
    emitted = set(re.findall(r'event="(patreon_[a-z_]+)"', WORKER_SOURCE.read_text(encoding="utf-8")))
    assert {
        "patreon_sync_completed",
        "patreon_sync_failed",
        "patreon_entitlement_changed",
        "patreon_tier_map_miss",
        "patreon_token_refreshed",
        "patreon_token_revoked",
        "patreon_retention_purged",
    } <= emitted
    assert emitted <= set(activity_logger.PATREON_ACTIVITY_TYPES)

    worker = _worker()
    with patch.object(activity_logger.ActivityLogger, "log_activity", return_value=True) as log_activity:
        for event in sorted(emitted):
            asyncio.run(worker._record_activity(event=event, outcome="completed", details={"reason": "unit"}))

    assert _written_types(log_activity) == sorted(emitted)


def test_retention_run_against_real_module_persists_act_cat_090():
    worker = _worker()
    with patch.object(db_patreon, "run_patreon_retention_purge", return_value={"proof_requests_purged": 3}), patch.object(
        activity_logger.ActivityLogger, "log_activity", return_value=True
    ) as log_activity, patch("src.workers.patreon_sync_worker.SystemMetrics.record_patreon_worker_heartbeat", return_value=True):
        result = asyncio.run(worker.run_once(mode="retention_only"))

    assert result.results[0].proof_requests_purged == 3
    assert _written_types(log_activity) == ["patreon_retention_purged"]


def test_successful_creator_token_refresh_records_act_cat_088():
    async def refresh_creator_token(*, db_module=None):
        return SimpleNamespace(status="refreshed", token_state_status="active")

    worker = _worker(client=SimpleNamespace(refresh_creator_token=refresh_creator_token), creator_token_refresh_enabled=True)
    with patch.object(activity_logger.ActivityLogger, "log_activity", return_value=True) as log_activity:
        result = asyncio.run(worker._run_token_refresh_job(job_id=None))

    assert result.status == "completed"
    assert _written_types(log_activity) == ["patreon_token_refreshed"]
    assert "access_token" not in str(log_activity.call_args.kwargs["details"])


def test_creator_token_401_records_act_cat_089_and_degrades_token_state():
    worker = _worker()
    with patch.object(db_patreon, "record_patreon_creator_token_degraded") as degrade, patch.object(
        activity_logger.ActivityLogger, "log_activity", return_value=True
    ) as log_activity:
        result = asyncio.run(
            worker._handle_provider_failure(
                error=PatreonUnauthorizedError(message="creator token rejected"),
                job_id=None,
                job_type="full_campaign",
            )
        )

    assert degrade.call_args.kwargs["status"] == "revoked"
    assert _written_types(log_activity) == ["patreon_token_revoked", "patreon_sync_failed"]
    assert result.status in {"retry", "failed"}


def test_worker_no_longer_calls_db_seams_that_do_not_exist():
    source = WORKER_SOURCE.read_text(encoding="utf-8")
    for name in (
        "record_sync_retry",
        "mark_entitlement_stale",
        "record_provider_health",
        "record_patreon_worker_heartbeat\", \"record_worker_heartbeat",
    ):
        assert name not in source, name
    assert callable(getattr(db_patreon, "record_patreon_activity", None))
