"""Opt-in live/sandbox Stripe smoke tests.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.10.

This file must be skipped by default. It must never require or print real
provider secrets during normal local acceptance.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest


RUN_FLAG = "RUN_STRIPE_E2E"
REQUIRED_LIVE_ENV = (
    "STRIPE_SECRET_KEY",
    "STRIPE_WEBHOOK_SECRET",
    "BILLING_S2S_BEARER_TOKEN",
    "STRIPE_LIVE_TEST_USER_HASH",
    "STRIPE_LIVE_TEST_PROJECT_HASH",
)
FORBIDDEN_LIVE_RESPONSE_FIELDS = {
    "stripe_customer_id",
    "stripe_subscription_id",
    "stripe_price_id",
    "stripe_product_id",
    "stripe_invoice_id",
    "stripe_payment_intent_id",
    "stripe_charge_id",
    "stripe_checkout_session_id",
    "stripe_portal_session_id",
    "stripe_event_id",
    "stripe_signature",
    "webhook_secret",
    "stripe_secret_key",
    "idempotency_key",
    "provider_id_hash",
    "provider_id_fingerprint",
}


@pytest.fixture
def live_stripe_config():
    if os.environ.get(RUN_FLAG, "").strip().lower() not in {"1", "true", "yes", "on"}:
        pytest.skip(f"live Stripe smoke disabled; set {RUN_FLAG}=true to run")

    missing = [name for name in REQUIRED_LIVE_ENV if not os.environ.get(name)]
    if missing:
        pytest.fail(
            f"live Stripe smoke was enabled but required env vars are missing: {', '.join(missing)}",
            pytrace=False,
        )

    return {name: os.environ[name] for name in REQUIRED_LIVE_ENV}


def _assert_no_live_secret_or_raw_stripe_id(response, *, context: str) -> None:
    try:
        payload: Any = response.json()
    except Exception:
        payload = response.text
    serialized = json.dumps(payload, sort_keys=True, default=str).lower() if not isinstance(payload, str) else payload.lower()
    for field in FORBIDDEN_LIVE_RESPONSE_FIELDS:
        assert field not in serialized, f"{context}: forbidden field `{field}` leaked in live Stripe smoke response"
    for raw_prefix in ("cus_", "sub_", "price_", "prod_", "in_", "pi_", "ch_", "cs_", "evt_", "whsec_", "sk_"):
        assert raw_prefix not in serialized, f"{context}: raw Stripe prefix `{raw_prefix}` leaked"
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_stripe_checkout_and_portal_are_explicit_opt_in_only(client, e2e_env, live_stripe_config, monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("BILLING_PORTAL_ENABLED", "true")
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("STRIPE_PORTAL_ENABLED", "true")

    user_hash = live_stripe_config["STRIPE_LIVE_TEST_USER_HASH"]
    project_hash = live_stripe_config["STRIPE_LIVE_TEST_PROJECT_HASH"]
    headers = {
        "Authorization": f"Bearer {live_stripe_config['BILLING_S2S_BEARER_TOKEN']}",
        "User-Agent": "stripe-live-opt-in-e2e-red-test",
        "Idempotency-Key": "stripe-live-smoke-idempotency-key",
    }
    checkout_path = f"/internal/users/{user_hash}/billing/checkout"
    portal_path = f"/internal/users/{user_hash}/billing/portal"

    checkout = await client.post(
        checkout_path,
        headers=headers,
        json={
            "project_hash": project_hash,
            "provider": "stripe",
            "intent_type": "subscription",
            "price_ref": {"ref_type": "lookup_key", "value": os.environ.get("STRIPE_LIVE_TEST_LOOKUP_KEY", "stripe_live_smoke_lookup_key")},
            "plan_code": "stripe_live_smoke_plan",
            "tier_code": "stripe_live_smoke_tier",
            "success_url": "https://example.test/success",
            "cancel_url": "https://example.test/cancel",
            "client_intent_ref": "stripe-live-smoke-intent",
        },
    )
    if checkout.status_code == 404 and "not found" in checkout.text.lower():
        pytest.fail(f"missing future Stripe checkout route {checkout_path}; live smoke cannot run until runtime wiring exists", pytrace=False)
    assert checkout.status_code in {200, 201, 202}
    _assert_no_live_secret_or_raw_stripe_id(checkout, context="live checkout")

    portal = await client.post(
        portal_path,
        headers=headers,
        json={"project_hash": project_hash, "provider": "stripe", "return_url": "https://example.test/billing"},
    )
    if portal.status_code == 404 and "not found" in portal.text.lower():
        pytest.fail(f"missing future Stripe portal route {portal_path}; live smoke cannot run until runtime wiring exists", pytrace=False)
    assert portal.status_code in {200, 202, 404}
    _assert_no_live_secret_or_raw_stripe_id(portal, context="live portal")
