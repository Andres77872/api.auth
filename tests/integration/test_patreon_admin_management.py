"""Integration tests for the ROOT Patreon admin management endpoints.

Mounts the already-registered ``admin_patreon`` router on an isolated FastAPI app
and drives it through ``TestClient`` with a faked ROOT session, asserting:
  - the dashboard pagination contract ({limit, offset, total, has_more}),
  - that no response leaks a forbidden field name or raw provider fragment,
  - resync dispatch + correlation id,
  - non-root callers are denied.
"""

from __future__ import annotations

from contextlib import ExitStack
from typing import Any, AsyncIterator
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI

from src.Util.Models import PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES
from src.middleware.error_handler import register_exception_handlers
from src.routes import admin_patreon


AUTH_HEADERS = {"Authorization": "Bearer test-root-session"}

RAW_FRAGMENTS = (
    "raw-patreon-id-leak",
    "should-never-be-serialized",
    "should-not-leak",
    "tier_id_fingerprint",
    "campaign_id_fingerprint",
    "last_error_redacted",
    "delivery_hash",
)


class _Session:
    user_id = "root-user"
    user_hash = "usr-root"
    username = "root"


class _PassLimiter:
    def check_sync_enqueue(self, **kwargs):  # noqa: ANN003
        return None


class _FakeConfig:
    sync_enabled = True
    campaign_ids = ("camp-raw-1",)


class _FakeUser:
    id = "internal-uid-1"


def _assert_no_forbidden_fields(obj: Any) -> None:
    if isinstance(obj, dict):
        for key, value in obj.items():
            normalized = str(key).lower().replace("-", "_")
            assert normalized not in PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES, f"forbidden field leaked: {key}"
            _assert_no_forbidden_fields(value)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_forbidden_fields(item)


def _assert_no_raw_fragments(raw_text: str) -> None:
    for fragment in RAW_FRAGMENTS:
        assert fragment not in raw_text, f"raw fragment leaked: {fragment}"


@pytest.fixture
async def client(monkeypatch) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_patreon.router)

    with ExitStack() as stack:
        stack.enter_context(patch("src.Util.decorators.validate_session", return_value=_Session()))
        stack.enter_context(patch.object(admin_patreon, "is_root_user", lambda user_id: True))
        stack.enter_context(patch.object(admin_patreon, "rate_limiter", _PassLimiter()))
        stack.enter_context(patch.object(admin_patreon, "load_patreon_config", lambda: _FakeConfig()))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as test_client:
            yield test_client


@pytest.mark.asyncio
async def test_entitlements_list_contract_and_redaction(client, monkeypatch):
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
            "patreon_user_id": "raw-patreon-id-leak",
        }
    ]
    monkeypatch.setattr(admin_patreon.db_patreon, "list_patreon_entitlements_admin", lambda **k: (rows, 5))

    resp = await client.get("/admin/patreon/entitlements?limit=2&offset=0", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["pagination"] == {"limit": 2, "offset": 0, "total": 5, "has_more": True}
    assert body["items"][0]["user_hash"] == "usr-aaa"
    _assert_no_forbidden_fields(body)
    _assert_no_raw_fragments(resp.text)


@pytest.mark.asyncio
async def test_sync_jobs_and_webhooks_redaction(client, monkeypatch):
    sync_rows = [
        {
            "job_id": "psj-1",
            "job_type": "user_member",
            "status": "retry",
            "priority": 5,
            "attempts": 1,
            "max_attempts": 8,
            "not_before": None,
            "source": "manual",
            "created_at": "2026-06-20T00:00:00Z",
            "updated_at": None,
            "completed_at": None,
            "has_error": 1,
            "last_error_redacted": "should-never-be-serialized",
        }
    ]
    webhook_rows = [
        {
            "delivery_id": "pwd-1",
            "event_type": "members:update",
            "status": "processed",
            "signature_valid": 1,
            "received_at": "2026-06-20T00:00:00Z",
            "processed_at": None,
            "delivery_hash": "should-not-leak",
        }
    ]
    monkeypatch.setattr(admin_patreon.db_patreon, "list_patreon_sync_jobs_admin", lambda **k: (sync_rows, 1))
    monkeypatch.setattr(admin_patreon.db_patreon, "list_patreon_webhooks_admin", lambda **k: (webhook_rows, 1))

    sync_resp = await client.get("/admin/patreon/sync-jobs", headers=AUTH_HEADERS)
    assert sync_resp.status_code == 200
    assert sync_resp.json()["items"][0]["has_error"] is True
    _assert_no_forbidden_fields(sync_resp.json())
    _assert_no_raw_fragments(sync_resp.text)

    wh_resp = await client.get("/admin/patreon/webhooks", headers=AUTH_HEADERS)
    assert wh_resp.status_code == 200
    assert wh_resp.json()["items"][0]["event_type"] == "members:update"
    _assert_no_raw_fragments(wh_resp.text)


@pytest.mark.asyncio
async def test_tier_map_list(client, monkeypatch):
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
    monkeypatch.setattr(admin_patreon.db_patreon, "list_patreon_tier_map_admin", lambda **k: (rows, 1))
    resp = await client.get("/admin/patreon/tier-map", headers=AUTH_HEADERS)
    assert resp.status_code == 200
    assert resp.json()["items"][0]["campaign_fingerprint"] == "abc123def456"
    _assert_no_raw_fragments(resp.text)


@pytest.mark.asyncio
async def test_resync_user_returns_correlation_id(client, monkeypatch):
    monkeypatch.setattr(admin_patreon, "get_user_by_hash", lambda h: _FakeUser())

    captured: dict[str, Any] = {}

    def _fake_enqueue(**kwargs):
        captured.update(kwargs)
        return admin_patreon.PatreonResyncAcceptedResponse(
            accepted=True, status="queued", user_hash=kwargs.get("user_hash"), correlation_id=kwargs.get("job_id")
        )

    monkeypatch.setattr(admin_patreon.patreon_sync, "enqueue_member_resync", _fake_enqueue)

    resp = await client.post(
        "/admin/patreon/resync",
        json={"scope": "user", "user_hash": "usr-aaa", "reason": "manual check"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["accepted"] is True
    assert body["status"] == "queued"
    assert body["correlation_id"]
    assert captured["user_id"] == "internal-uid-1"


@pytest.mark.asyncio
async def test_resync_all_enqueues_full_campaign(client, monkeypatch):
    captured: dict[str, Any] = {}

    def _fake_job(**kwargs):
        captured.update(kwargs)
        return {"job_id": kwargs.get("job_id")}

    monkeypatch.setattr(admin_patreon.db_patreon, "enqueue_patreon_sync_job", _fake_job)

    resp = await client.post(
        "/admin/patreon/resync",
        json={"scope": "all", "reason": "nightly"},
        headers=AUTH_HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    assert captured["job_type"] == admin_patreon.patreon_sync.JOB_TYPE_FULL_CAMPAIGN
    assert captured["campaign_id"] is None


@pytest.mark.asyncio
async def test_non_root_denied(monkeypatch):
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(admin_patreon.router)

    with ExitStack() as stack:
        stack.enter_context(patch("src.Util.decorators.validate_session", return_value=_Session()))
        stack.enter_context(patch.object(admin_patreon, "is_root_user", lambda user_id: False))
        stack.enter_context(
            patch.object(admin_patreon.db_patreon, "list_patreon_entitlements_admin", lambda **k: ([], 0))
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as test_client:
            resp = await test_client.get("/admin/patreon/entitlements", headers=AUTH_HEADERS)
        assert resp.status_code == 403
