"""ROOT-only Patreon admin management endpoint tests (list reads + resync)."""

from __future__ import annotations

import json

import pytest

from src.Util.error_handler import (
    AuthorizationError,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from src.Util.patreon.rate_limit import PatreonRateLimitExceeded
from src.routes import admin_patreon as route


class _Ctx:
    user_id = "root-user"


class _FakeUser:
    def __init__(self, user_id: str) -> None:
        self.id = user_id


class _FakeConfig:
    def __init__(self, sync_enabled: bool = True, campaign_ids=("camp-raw-1",)) -> None:
        self.sync_enabled = sync_enabled
        self.campaign_ids = tuple(campaign_ids)


class _PassLimiter:
    def __init__(self) -> None:
        self.calls = 0

    def check_sync_enqueue(self, **kwargs):  # noqa: ANN003
        self.calls += 1
        return None


class _BlockLimiter:
    def check_sync_enqueue(self, **kwargs):  # noqa: ANN003
        raise PatreonRateLimitExceeded(bucket="sync_enqueue", retry_after=42, limit=1)


def _root(monkeypatch) -> None:
    monkeypatch.setattr(route, "is_root_user", lambda user_id: True)


# ---------------------------------------------------------------------------
# Root gating
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "handler",
    [
        route.list_admin_patreon_entitlements,
        route.list_admin_patreon_tier_map,
        route.list_admin_patreon_sync_jobs,
        route.list_admin_patreon_webhooks,
    ],
)
async def test_admin_list_endpoints_require_root(monkeypatch, handler):
    monkeypatch.setattr(route, "is_root_user", lambda user_id: False)
    with pytest.raises(AuthorizationError):
        await handler.__wrapped__(credentials=None, log_context=_Ctx())


@pytest.mark.asyncio
async def test_admin_detail_requires_root(monkeypatch):
    monkeypatch.setattr(route, "is_root_user", lambda user_id: False)
    with pytest.raises(AuthorizationError):
        await route.get_admin_patreon_entitlement.__wrapped__(
            user_hash="usr-1", credentials=None, log_context=_Ctx()
        )


@pytest.mark.asyncio
async def test_admin_resync_requires_root(monkeypatch):
    monkeypatch.setattr(route, "is_root_user", lambda user_id: False)
    with pytest.raises(AuthorizationError):
        await route.enqueue_admin_patreon_resync.__wrapped__(
            scope="all", user_hash=None, reason=None, force=False,
            credentials=None,
            log_context=_Ctx(),
        )


# ---------------------------------------------------------------------------
# Entitlements list: mapping, pagination, redaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_entitlements_list_maps_rows_and_pagination(monkeypatch):
    _root(monkeypatch)
    rows = [
        {
            "user_hash": "usr-aaa",
            "display_name": "alice",
            "entitlement_status": "active",
            "link_status": "linked",
            "plan_code": "tier1",
            "tier_code": "gold",
            "tier_name": "Gold",
            "last_synced_at": "2026-06-20T00:00:00Z",
            "updated_at": "2026-06-20T01:00:00Z",
            # Injected forbidden field must never reach the response.
            "patreon_user_id": "raw-patreon-id-leak",
        }
    ]
    monkeypatch.setattr(
        route.db_patreon,
        "list_patreon_entitlements_admin",
        lambda **kwargs: (rows, 25),
    )
    resp = await route.list_admin_patreon_entitlements.__wrapped__(
        limit=10, offset=0, status=None, plan_code=None, credentials=None, log_context=_Ctx()
    )

    assert resp["success"] is True
    assert resp["pagination"] == {"limit": 10, "offset": 0, "total": 25, "has_more": True}
    item = resp["items"][0]
    assert item["user_hash"] == "usr-aaa"
    assert item["status"] == "active"
    assert item["link_status"] == "linked"
    assert item["plan_code"] == "tier1"
    serialized = json.dumps(resp, sort_keys=True)
    assert "raw-patreon-id-leak" not in serialized
    assert "patreon_user_id" not in serialized


@pytest.mark.asyncio
async def test_entitlements_list_has_more_false_on_last_page(monkeypatch):
    _root(monkeypatch)
    monkeypatch.setattr(
        route.db_patreon, "list_patreon_entitlements_admin", lambda **kwargs: ([], 10)
    )
    resp = await route.list_admin_patreon_entitlements.__wrapped__(
        limit=10, offset=5, status=None, plan_code=None, credentials=None, log_context=_Ctx()
    )
    assert resp["pagination"]["has_more"] is False


# ---------------------------------------------------------------------------
# Tier map: fingerprints exposed under safe alias names only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_map_list_exposes_safe_fingerprints(monkeypatch):
    _root(monkeypatch)
    rows = [
        {
            "campaign_fingerprint": "abc123def456",
            "campaign_name": "Main",
            "tier_fingerprint": "fed654cba321",
            "plan_code": "tier1",
            "tier_code": "gold",
            "tier_name": "Gold",
            "priority": 10,
            "active": 1,
            "effective_from": "2026-01-01T00:00:00Z",
            "effective_until": None,
        }
    ]
    monkeypatch.setattr(route.db_patreon, "list_patreon_tier_map_admin", lambda **kwargs: (rows, 1))
    resp = await route.list_admin_patreon_tier_map.__wrapped__(
        limit=100, offset=0, active=None, credentials=None, log_context=_Ctx()
    )
    item = resp["items"][0]
    assert item["campaign_fingerprint"] == "abc123def456"
    assert item["tier_fingerprint"] == "fed654cba321"
    assert item["active"] is True
    # The forbidden raw fingerprint field names must not appear at all.
    serialized = json.dumps(resp, sort_keys=True)
    assert "tier_id_fingerprint" not in serialized
    assert "campaign_id_fingerprint" not in serialized


# ---------------------------------------------------------------------------
# Sync jobs: errors reduced to a boolean, no raw error text
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sync_jobs_list_reduces_error_to_flag(monkeypatch):
    _root(monkeypatch)
    rows = [
        {
            "job_id": "psj-1",
            "job_type": "user_member",
            "status": "retry",
            "priority": 5,
            "attempts": 2,
            "max_attempts": 8,
            "not_before": "2026-06-20T00:00:00Z",
            "source": "manual",
            "created_at": "2026-06-20T00:00:00Z",
            "updated_at": "2026-06-20T00:05:00Z",
            "completed_at": None,
            "has_error": 1,
            "last_error_redacted": "should-never-be-serialized",
        }
    ]
    monkeypatch.setattr(route.db_patreon, "list_patreon_sync_jobs_admin", lambda **kwargs: (rows, 1))
    resp = await route.list_admin_patreon_sync_jobs.__wrapped__(
        limit=50, offset=0, status="retry", credentials=None, log_context=_Ctx()
    )
    item = resp["items"][0]
    assert item["has_error"] is True
    assert item["job_id"] == "psj-1"
    serialized = json.dumps(resp, sort_keys=True)
    assert "should-never-be-serialized" not in serialized
    assert "last_error_redacted" not in serialized


@pytest.mark.asyncio
async def test_webhooks_list_maps_safe_fields(monkeypatch):
    _root(monkeypatch)
    rows = [
        {
            "delivery_id": "pwd-1",
            "event_type": "members:update",
            "status": "processed",
            "signature_valid": 1,
            "received_at": "2026-06-20T00:00:00Z",
            "processed_at": "2026-06-20T00:00:01Z",
            "delivery_hash": b"should-not-leak",
        }
    ]
    monkeypatch.setattr(route.db_patreon, "list_patreon_webhooks_admin", lambda **kwargs: (rows, 1))
    resp = await route.list_admin_patreon_webhooks.__wrapped__(
        limit=50, offset=0, status=None, credentials=None, log_context=_Ctx()
    )
    item = resp["items"][0]
    assert item["event_type"] == "members:update"
    assert item["signature_valid"] is True
    serialized = json.dumps(resp, sort_keys=True)
    assert "delivery_hash" not in serialized


# ---------------------------------------------------------------------------
# Detail endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detail_404_when_user_missing(monkeypatch):
    _root(monkeypatch)
    monkeypatch.setattr(route.db_patreon, "get_entitlement_by_user_hash", lambda h: None)
    with pytest.raises(NotFoundError):
        await route.get_admin_patreon_entitlement.__wrapped__(
            user_hash="usr-missing", credentials=None, log_context=_Ctx()
        )


@pytest.mark.asyncio
async def test_detail_maps_safe_entitlement(monkeypatch):
    _root(monkeypatch)
    row = {
        "user_hash": "usr-aaa",
        "external_source": "patreon",
        "entitlement_status": "active",
        "link_status": "linked",
        "plan_code": "tier1",
        "tier_code": "gold",
        "tier_name": "Gold",
        "next_renewal_at": None,
        "grace_period_until": None,
        "last_synced_at": None,
        "stale_after": None,
        "classification_version": 1,
    }
    monkeypatch.setattr(route.db_patreon, "get_entitlement_by_user_hash", lambda h: row)
    resp = await route.get_admin_patreon_entitlement.__wrapped__(
        user_hash="usr-aaa", credentials=None, log_context=_Ctx()
    )
    assert resp["user_hash"] == "usr-aaa"
    assert resp["entitlement"]["plan_code"] == "tier1"
    assert resp["entitlement"]["link_status"] == "linked"


# ---------------------------------------------------------------------------
# Resync dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resync_disabled_when_sync_off(monkeypatch):
    _root(monkeypatch)
    monkeypatch.setattr(route, "load_patreon_config", lambda: _FakeConfig(sync_enabled=False))
    resp = await route.enqueue_admin_patreon_resync.__wrapped__(
        scope="all", user_hash=None, reason=None, force=False,
        credentials=None,
        log_context=_Ctx(),
    )
    assert resp["accepted"] is False
    assert resp["status"] == "disabled"


@pytest.mark.asyncio
async def test_resync_rate_limited(monkeypatch):
    _root(monkeypatch)
    monkeypatch.setattr(route, "load_patreon_config", lambda: _FakeConfig(sync_enabled=True))
    monkeypatch.setattr(route, "rate_limiter", _BlockLimiter())
    with pytest.raises(RateLimitError):
        await route.enqueue_admin_patreon_resync.__wrapped__(
            scope="all", user_hash=None, reason=None, force=False,
            credentials=None,
            log_context=_Ctx(),
        )


@pytest.mark.asyncio
async def test_resync_user_requires_user_hash(monkeypatch):
    _root(monkeypatch)
    monkeypatch.setattr(route, "load_patreon_config", lambda: _FakeConfig(sync_enabled=True))
    monkeypatch.setattr(route, "rate_limiter", _PassLimiter())
    with pytest.raises(ValidationError):
        await route.enqueue_admin_patreon_resync.__wrapped__(
            scope="user", user_hash=None, reason=None, force=False,
            credentials=None,
            log_context=_Ctx(),
        )


@pytest.mark.asyncio
async def test_resync_user_unknown_user_404(monkeypatch):
    _root(monkeypatch)
    monkeypatch.setattr(route, "load_patreon_config", lambda: _FakeConfig(sync_enabled=True))
    monkeypatch.setattr(route, "rate_limiter", _PassLimiter())
    monkeypatch.setattr(route, "get_user_by_hash", lambda h: None)
    with pytest.raises(NotFoundError):
        await route.enqueue_admin_patreon_resync.__wrapped__(
            scope="user", user_hash="usr-missing", reason="x", force=False,
            credentials=None,
            log_context=_Ctx(),
        )


@pytest.mark.asyncio
async def test_resync_user_enqueues_member_resync(monkeypatch):
    _root(monkeypatch)
    monkeypatch.setattr(route, "load_patreon_config", lambda: _FakeConfig(sync_enabled=True))
    monkeypatch.setattr(route, "rate_limiter", _PassLimiter())
    monkeypatch.setattr(route, "get_user_by_hash", lambda h: _FakeUser("internal-uid-1"))

    captured = {}

    def _fake_enqueue(**kwargs):
        captured.update(kwargs)
        return route.PatreonResyncAcceptedResponse(
            accepted=True, status="queued", user_hash=kwargs.get("user_hash"), correlation_id=kwargs.get("job_id")
        )

    monkeypatch.setattr(route.patreon_sync, "enqueue_member_resync", _fake_enqueue)
    # Guard: the full-campaign path must NOT be used for scope=user.
    monkeypatch.setattr(
        route.db_patreon,
        "enqueue_patreon_sync_job",
        lambda **kwargs: pytest.fail("scope=user must not enqueue a full_campaign job"),
    )

    resp = await route.enqueue_admin_patreon_resync.__wrapped__(
        scope="user", user_hash="usr-aaa", reason="manual check", force=False,
        credentials=None,
        log_context=_Ctx(),
    )
    assert resp["accepted"] is True
    assert resp["status"] == "queued"
    assert resp["correlation_id"]
    assert captured["user_id"] == "internal-uid-1"
    assert captured["user_hash"] == "usr-aaa"
    assert captured["job_type"] == route.patreon_sync.JOB_TYPE_USER_MEMBER


@pytest.mark.asyncio
async def test_resync_all_enqueues_full_campaign_sweep(monkeypatch):
    _root(monkeypatch)
    monkeypatch.setattr(route, "load_patreon_config", lambda: _FakeConfig(sync_enabled=True))
    monkeypatch.setattr(route, "rate_limiter", _PassLimiter())

    captured = {}

    def _fake_enqueue_job(**kwargs):
        captured.update(kwargs)
        return {"job_id": kwargs.get("job_id"), "status": "pending"}

    monkeypatch.setattr(route.db_patreon, "enqueue_patreon_sync_job", _fake_enqueue_job)

    resp = await route.enqueue_admin_patreon_resync.__wrapped__(
        scope="all", user_hash=None, reason="nightly", force=False,
        credentials=None,
        log_context=_Ctx(),
    )
    assert resp["accepted"] is True
    assert resp["status"] == "queued"
    assert captured["job_type"] == route.patreon_sync.JOB_TYPE_FULL_CAMPAIGN
    assert captured["campaign_id"] is None
    assert captured["user_id"] is None
