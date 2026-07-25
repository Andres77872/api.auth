"""Phase 1 RED tests for the Patreon sync worker and retention loop.

Trace: `.dev/sdd/changes/patreon-account-link/tasks.md` task `1.12`.

The future worker module is imported only inside tests so this file collects
before production Patreon code exists. Missing worker APIs fail with explicit
RED messages instead of import-time errors.
"""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "patreon"


class FakePatreonRateLimited(Exception):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"rate limited; retry after {retry_after_seconds}s")
        self.retry_after_seconds = retry_after_seconds


class FakePatreonUnauthorized(Exception):
    pass


def _member_fixture(name: str) -> dict[str, Any]:
    path = FIXTURE_ROOT / "members" / name
    return json.loads(path.read_text(encoding="utf-8"))


def _active_member() -> dict[str, Any]:
    return _member_fixture("active_mapped_member.json")["data"][0]


def _former_member() -> dict[str, Any]:
    return _member_fixture("former_member.json")["data"][0]


def _unknown_tier_member() -> dict[str, Any]:
    return _member_fixture("unknown_tier_member.json")["data"][0]


@dataclass
class FakePatreonClient:
    campaign_pages: dict[tuple[str, str | None], dict[str, Any]] = field(default_factory=dict)
    member_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    fail_with: Exception | None = None
    calls: list[tuple[str, Any]] = field(default_factory=list)

    async def list_campaign_members(self, campaign_id: str, *, page_cursor: str | None = None, **_kwargs) -> dict[str, Any]:
        self.calls.append(("list_campaign_members", campaign_id, page_cursor))
        if self.fail_with is not None:
            raise self.fail_with
        return self.campaign_pages.get((campaign_id, page_cursor), {"data": [], "next_cursor": None})

    async def get_member(self, member_id: str, **_kwargs) -> dict[str, Any]:
        self.calls.append(("get_member", member_id))
        if self.fail_with is not None:
            raise self.fail_with
        return self.member_results[member_id]

    async def refresh_creator_token(self) -> None:
        self.calls.append(("refresh_creator_token", None))
        if self.fail_with is not None:
            raise self.fail_with


@dataclass
class FakePatreonSyncStore:
    campaigns: list[dict[str, Any]] = field(default_factory=list)
    jobs: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)
    current_entitlements: list[dict[str, Any]] = field(default_factory=list)
    activities: list[dict[str, Any]] = field(default_factory=list)
    stale_marks: list[dict[str, Any]] = field(default_factory=list)
    retry_records: list[dict[str, Any]] = field(default_factory=list)
    completed_jobs: list[dict[str, Any]] = field(default_factory=list)
    heartbeats: list[dict[str, Any]] = field(default_factory=list)
    health_events: list[dict[str, Any]] = field(default_factory=list)
    purge_calls: list[dict[str, Any]] = field(default_factory=list)
    destructive_delete_attempts: list[dict[str, Any]] = field(default_factory=list)

    def list_enabled_patreon_campaigns(self) -> list[dict[str, Any]]:
        return list(self.campaigns)

    def list_enabled_campaigns(self) -> list[dict[str, Any]]:
        return self.list_enabled_patreon_campaigns()

    def claim_patreon_sync_jobs(self, *, worker_id: str, limit: int, lease_seconds: int) -> list[dict[str, Any]]:
        claimed: list[dict[str, Any]] = []
        for job in self.jobs:
            if job.get("status", "pending") != "pending":
                continue
            job["status"] = "processing"
            job["claimed_by"] = worker_id
            job["lease_seconds"] = lease_seconds
            claimed.append(dict(job))
            if len(claimed) >= int(limit):
                break
        return claimed

    def claim_sync_jobs(self, **kwargs) -> list[dict[str, Any]]:
        return self.claim_patreon_sync_jobs(**kwargs)

    def record_member_observation(self, **kwargs) -> dict[str, Any]:
        self.observations.append(dict(kwargs))
        return {"status": "observed", **kwargs}

    def upsert_member_observation(self, **kwargs) -> dict[str, Any]:
        return self.record_member_observation(**kwargs)

    def upsert_current_entitlement(self, **kwargs) -> dict[str, Any]:
        self.current_entitlements.append(dict(kwargs))
        return {"status": "upserted", **kwargs}

    def append_entitlement_history(self, **kwargs) -> dict[str, Any]:
        self.current_entitlements.append({"history": dict(kwargs)})
        return {"status": "history_appended", **kwargs}

    def record_patreon_activity(self, **kwargs) -> dict[str, Any]:
        self.activities.append(dict(kwargs))
        return {"status": "recorded", **kwargs}

    def record_activity(self, **kwargs) -> dict[str, Any]:
        return self.record_patreon_activity(**kwargs)

    def mark_entitlement_stale(self, **kwargs) -> dict[str, Any]:
        self.stale_marks.append(dict(kwargs))
        return {"status": "stale", **kwargs}

    def record_sync_retry(self, **kwargs) -> dict[str, Any]:
        self.retry_records.append(dict(kwargs))
        return {"status": "retry", **kwargs}

    def complete_sync_job(self, **kwargs) -> dict[str, Any]:
        self.completed_jobs.append(dict(kwargs))
        return {"status": kwargs.get("status", "completed"), **kwargs}

    def record_worker_heartbeat(self, **kwargs) -> dict[str, Any]:
        self.heartbeats.append(dict(kwargs))
        return {"status": "heartbeat", **kwargs}

    def record_patreon_worker_heartbeat(self, **kwargs) -> dict[str, Any]:
        return self.record_worker_heartbeat(**kwargs)

    def record_provider_health(self, **kwargs) -> dict[str, Any]:
        self.health_events.append(dict(kwargs))
        return {"status": "health", **kwargs}

    def purge_expired_patreon_proofs(self, **kwargs) -> dict[str, Any]:
        self.purge_calls.append({"kind": "proofs", **kwargs})
        return {"purged": 1}

    def purge_expired_webhook_deliveries(self, **kwargs) -> dict[str, Any]:
        self.purge_calls.append({"kind": "webhook_hashes", **kwargs})
        return {"purged": 1}

    def purge_expired_raw_payloads(self, **kwargs) -> dict[str, Any]:
        self.purge_calls.append({"kind": "raw_payloads", **kwargs})
        return {"purged": 1}

    def delete_patreon_history(self, **kwargs) -> None:
        self.destructive_delete_attempts.append(dict(kwargs))
        raise AssertionError("sync worker must never destructively delete Patreon link/snapshot/unlink history")


def _require_worker_class():
    try:
        module = import_module("src.workers.patreon_sync_worker")
    except ImportError as exc:
        pytest.fail(
            "missing future module `src.workers.patreon_sync_worker`; task 8.1 must implement "
            f"the Patreon sync worker before this RED proof can pass ({exc})",
            pytrace=False,
        )
    for class_name in ("PatreonSyncWorker", "PatreonWorker"):
        worker_class = getattr(module, class_name, None)
        if worker_class is not None:
            return worker_class
    pytest.fail("future Patreon worker module must expose `PatreonSyncWorker`", pytrace=False)


def _worker_config() -> SimpleNamespace:
    return SimpleNamespace(
        sync_enabled=True,
        worker_batch_size=25,
        worker_lease_seconds=60,
        worker_poll_seconds=1,
        stale_after_seconds=86_400,
        retention_purge_interval_seconds=1,
        proof_retention_after_expiry_hours=24,
        webhook_delivery_retention_days=90,
        raw_payload_retention_days=30,
        preserve_history_indefinitely=True,
    )


def _make_worker(*, fake_redis, client: FakePatreonClient, store: FakePatreonSyncStore):
    worker_class = _require_worker_class()
    attempts = (
        {"worker_id": "patreon-red-worker", "client": client, "db_module": store, "redis": fake_redis, "config": _worker_config()},
        {"worker_id": "patreon-red-worker", "patreon_client": client, "db_module": store, "redis": fake_redis, "config": _worker_config()},
        {"worker_id": "patreon-red-worker", "client": client, "db": store, "redis": fake_redis, "config": _worker_config()},
        {"worker_id": "patreon-red-worker", "patreon_client": client, "db": store, "redis": fake_redis, "config": _worker_config()},
    )
    errors: list[str] = []
    for kwargs in attempts:
        try:
            return worker_class(**kwargs)
        except TypeError as exc:
            errors.append(str(exc))
    pytest.fail(
        "PatreonSyncWorker must accept injected fake client/db/redis/config for hermetic RED tests; "
        f"constructor errors: {errors}",
        pytrace=False,
    )


async def _run_worker_once(worker: Any, **kwargs) -> Any:
    for method_name in ("run_once", "drain_once", "process_once", "sync_once"):
        method = getattr(worker, method_name, None)
        if method is None:
            continue
        try:
            result = method(**kwargs)
        except TypeError:
            result = method()
        if inspect.isawaitable(result):
            return await result
        return result
    pytest.fail("PatreonSyncWorker must expose a one-shot method (`run_once`/`drain_once`/`process_once`)", pytrace=False)


@pytest.mark.asyncio
async def test_full_campaign_sweep_paginates_all_configured_campaigns_without_raw_id_leak(fake_redis):
    store = FakePatreonSyncStore(
        campaigns=[{"campaign_id": "campaign-mw-alpha"}, {"campaign_id": "campaign-mw-beta"}],
    )
    client = FakePatreonClient(
        campaign_pages={
            ("campaign-mw-alpha", None): {"data": [_active_member()], "next_cursor": "cursor-alpha-2"},
            ("campaign-mw-alpha", "cursor-alpha-2"): {"data": [_former_member()], "next_cursor": None},
            ("campaign-mw-beta", None): {"data": [_active_member()], "next_cursor": None},
        }
    )
    worker = _make_worker(fake_redis=fake_redis, client=client, store=store)

    await _run_worker_once(worker, mode="full_campaign_sweep")

    assert client.calls == [
        ("list_campaign_members", "campaign-mw-alpha", None),
        ("list_campaign_members", "campaign-mw-alpha", "cursor-alpha-2"),
        ("list_campaign_members", "campaign-mw-beta", None),
    ]
    assert len(store.observations) == 3
    assert all("campaign-mw-" not in str(item).lower() for item in store.activities), "activities must not leak raw campaign IDs"


@pytest.mark.asyncio
async def test_per_member_manual_resync_claims_one_job_and_completes_idempotently(fake_redis):
    member = _active_member()
    store = FakePatreonSyncStore(
        jobs=[{"job_id": "sync-job-001", "kind": "manual_member", "member_id": member["id"], "status": "pending"}],
    )
    client = FakePatreonClient(member_results={member["id"]: {"data": [member]}})
    worker = _make_worker(fake_redis=fake_redis, client=client, store=store)

    await _run_worker_once(worker)

    assert ("get_member", member["id"]) in client.calls
    assert store.completed_jobs, "manual per-member resync must complete or safely finalize the claimed job"
    assert len(store.completed_jobs) == 1, "a retried manual job must not create duplicate completion side effects"


@pytest.mark.asyncio
async def test_provider_429_backs_off_and_marks_existing_snapshot_stale_without_downgrade(fake_redis):
    store = FakePatreonSyncStore(campaigns=[{"campaign_id": "campaign-mw-alpha"}])
    client = FakePatreonClient(fail_with=FakePatreonRateLimited(retry_after_seconds=42))
    worker = _make_worker(fake_redis=fake_redis, client=client, store=store)

    await _run_worker_once(worker, mode="full_campaign_sweep")

    assert store.retry_records or store.stale_marks, "Patreon 429 must produce backoff/stale evidence"
    assert any("42" in str(record) for record in store.retry_records + store.stale_marks), "retry_after_seconds must be preserved"
    assert not any(record.get("status") in {"free", "revoked"} for record in store.current_entitlements), (
        "rate limits must not destructively downgrade current entitlement"
    )


@pytest.mark.asyncio
async def test_unknown_tier_records_tier_map_miss_and_fails_safe_without_paid_grant(fake_redis):
    unknown = _unknown_tier_member()
    store = FakePatreonSyncStore(campaigns=[{"campaign_id": "campaign-mw-alpha"}])
    client = FakePatreonClient(campaign_pages={("campaign-mw-alpha", None): {"data": [unknown], "next_cursor": None}})
    worker = _make_worker(fake_redis=fake_redis, client=client, store=store)

    await _run_worker_once(worker, mode="full_campaign_sweep")

    assert any("tier" in str(activity).lower() and "miss" in str(activity).lower() for activity in store.activities), (
        "unknown active tiers must create internal tier-map-miss activity"
    )
    assert not any(record.get("plan_code") not in {None, "free"} for record in store.current_entitlements), (
        "unknown tiers must not grant paid entitlement"
    )


@pytest.mark.asyncio
async def test_creator_token_failure_reports_degraded_health_and_preserves_last_known_snapshot(fake_redis):
    store = FakePatreonSyncStore(campaigns=[{"campaign_id": "campaign-mw-alpha"}])
    client = FakePatreonClient(fail_with=FakePatreonUnauthorized("creator token expired"))
    worker = _make_worker(fake_redis=fake_redis, client=client, store=store)

    await _run_worker_once(worker, mode="full_campaign_sweep")

    assert store.health_events or store.stale_marks, "creator-token failure must be observable as degraded health/stale state"
    assert not any(record.get("status") in {"free", "revoked"} for record in store.current_entitlements), (
        "creator-token failure alone must not downgrade entitlement"
    )


@pytest.mark.asyncio
async def test_worker_records_heartbeat_after_one_shot_processing(fake_redis):
    store = FakePatreonSyncStore(campaigns=[{"campaign_id": "campaign-mw-alpha"}])
    client = FakePatreonClient(campaign_pages={("campaign-mw-alpha", None): {"data": [_active_member()], "next_cursor": None}})
    worker = _make_worker(fake_redis=fake_redis, client=client, store=store)

    await _run_worker_once(worker, mode="full_campaign_sweep")

    assert store.heartbeats, "worker heartbeat must be recorded for system health"
    assert all("creator_access_token" not in str(heartbeat).lower() for heartbeat in store.heartbeats)


@pytest.mark.asyncio
async def test_retention_purge_preserves_history_and_caps_proofs_webhook_hashes_and_raw_payloads(fake_redis):
    store = FakePatreonSyncStore()
    client = FakePatreonClient()
    worker = _make_worker(fake_redis=fake_redis, client=client, store=store)

    await _run_worker_once(worker, mode="retention_only", now=datetime(2026, 6, 15, tzinfo=timezone.utc))

    purge_kinds = {call["kind"] for call in store.purge_calls}
    assert {"proofs", "webhook_hashes", "raw_payloads"} <= purge_kinds
    assert not store.destructive_delete_attempts, "retention must never delete link/snapshot/unlink history"

    proof_call = next(call for call in store.purge_calls if call["kind"] == "proofs")
    webhook_call = next(call for call in store.purge_calls if call["kind"] == "webhook_hashes")
    raw_payload_call = next(call for call in store.purge_calls if call["kind"] == "raw_payloads")
    serialized_retention = str((proof_call, webhook_call, raw_payload_call)).lower()
    assert "24" in serialized_retention or str(timedelta(hours=24)) in serialized_retention
    assert "90" in serialized_retention
    assert "30" in serialized_retention
