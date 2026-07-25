"""Contract test for the path-scoped Stripe webhook route (group-keyed observe).

Verifies that `POST /webhooks/stripe/{billing_group_hash}` selects the group's own webhook
secret deterministically and threads the URL-resolved billing_group_id into the entitlement
write (overriding any group implied by event metadata).
"""

from __future__ import annotations

import importlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.Util.billing.provider import BillingClassificationResult, VerifiedProviderEvent


ROUTE_MODULE = "src.routes.stripe_webhooks"
GROUP_HASH = "BG_HASH_URL"
GROUP_PATH = f"/webhooks/stripe/{GROUP_HASH}"


@asynccontextmanager
async def _client():
    module = importlib.import_module(ROUTE_MODULE)
    app = FastAPI(title="Stripe webhook group route test")
    app.include_router(module.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _event() -> VerifiedProviderEvent:
    return VerifiedProviderEvent(
        provider="stripe",
        event_type="customer.subscription.updated",
        event_id_hmac=b"1" * 32,
        event_id_fingerprint="aaaaaaaaaaaa",
        raw_body_sha256=b"2" * 32,
        received_at=datetime.now(timezone.utc).replace(microsecond=0),
        payload={
            "type": "customer.subscription.updated",
            "data": {
                "object": {
                    "metadata": {
                        "user_hash": "usrh_x",
                        "project_hash": "prjh_x",
                        "plan_code": "plus",
                        "tier_code": "plus",
                        "subscription_ref": "bsub-x",
                    }
                }
            },
        },
    )


@pytest.mark.asyncio
async def test_path_scoped_webhook_threads_url_group_into_observe(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    module = importlib.import_module(ROUTE_MODULE)

    captured: dict[str, Any] = {}

    monkeypatch.setattr(module, "get_billing_group_by_hash", lambda **_: {"id": "bg-url-1"})
    monkeypatch.setattr(
        module,
        "get_stripe_account_secrets_for_group",
        lambda **_: SimpleNamespace(webhook_secret="whsec_group_secret"),
    )
    monkeypatch.setattr(module, "build_verified_provider_event", lambda **_: _event())
    monkeypatch.setattr(
        module,
        "classify_stripe_event",
        lambda **_: BillingClassificationResult(
            provider="stripe", event_type="customer.subscription.updated", subscription_status="active", reason="ok"
        ),
    )
    # Metadata resolves to a DIFFERENT group; the URL group must win.
    monkeypatch.setattr(
        module,
        "resolve_user_billing_group",
        lambda **_: {"user_id": "usr-1", "project_id": "prj-1", "billing_group_id": "meta-group"},
    )
    monkeypatch.setattr(module, "record_webhook_delivery", lambda **_: {"delivery_status": "accepted"})

    def _capture_observe(**kwargs: Any):
        captured.update(kwargs)
        return {"status": "active"}

    monkeypatch.setattr(module, "observe_subscription", _capture_observe)
    monkeypatch.setattr(module, "_invalidate_user_sessions", lambda *_a, **_k: None)

    async with _client() as client:
        resp = await client.post(GROUP_PATH, content=b"{}", headers={"Stripe-Signature": "sig", "User-Agent": "t"})

    assert resp.status_code == 200
    assert captured.get("billing_group_id") == "bg-url-1", captured
    assert captured.get("user_id") == "usr-1"
    # never carries a project_id on the group-scoped subscription write
    assert "project_id" not in captured


@pytest.mark.asyncio
async def test_path_scoped_webhook_503_when_group_not_ready(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    module = importlib.import_module(ROUTE_MODULE)
    monkeypatch.setattr(module, "get_billing_group_by_hash", lambda **_: None)

    async with _client() as client:
        resp = await client.post(GROUP_PATH, content=b"{}", headers={"Stripe-Signature": "sig", "User-Agent": "t"})

    assert resp.status_code == 503
