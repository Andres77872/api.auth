"""A Stripe plan transition refreshes the cached plan without signing the user out.

Runs the real subscription write path of the webhook route; only the customer upsert,
the subscription procedure, provider-ref encryption and Redis are stubbed.
"""

from __future__ import annotations

import json

import fakeredis
import pytest

from src.Util.billing.provider import BillingClassificationResult, VerifiedProviderEvent
from src.Util.cache_manager import cache_manager
from src.routes import stripe_webhooks


def _seed(fake, key, payload):
    fake.set(key, json.dumps(payload))


@pytest.mark.asyncio
async def test_plan_transition_keeps_access_sessions_and_drops_cached_validation(monkeypatch):
    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(cache_manager, "redis", fake)
    _seed(fake, "session:jti-own", {"user_id": "u-1"})
    _seed(fake, "session_full:jti-own", {"user_id": "u-1"})
    _seed(fake, "session:jti-other", {"user_id": "u-2"})
    _seed(fake, "session_full:jti-other", {"user_id": "u-2"})

    observed: list[dict] = []

    async def _upsert_customer(**_kwargs):
        return "bcust-1"

    def _observe(**kwargs):
        observed.append(kwargs)
        return {"subscription_id": kwargs["subscription_id"]}

    monkeypatch.setattr(stripe_webhooks, "_upsert_customer_from_event", _upsert_customer)
    monkeypatch.setattr(stripe_webhooks, "_provider_ref_evidence", lambda *_a, **_k: None)
    monkeypatch.setattr(stripe_webhooks, "observe_subscription", _observe)

    event = VerifiedProviderEvent(
        provider="stripe",
        event_type="customer.subscription.updated",
        event_id_hmac=b"evt-hmac",
        event_id_fingerprint="evt-fp",
        raw_body_sha256=b"\x00" * 32,
        payload={"data": {"object": {"object": "subscription", "metadata": {}}}},
    )
    classification = BillingClassificationResult(
        provider="stripe",
        event_type=event.event_type,
        subscription_status="active",
    )

    result = await stripe_webhooks._persist_classification(
        event,
        classification,
        scope={"user_id": "u-1"},
        billing_group_id="bg-1",
    )

    assert result is not None
    assert [row["normalized_status"] for row in observed] == ["active"]
    assert fake.exists("session:jti-own")  # still signed in
    assert not fake.exists("session_full:jti-own")  # plan recomputed on the next validate
    assert fake.exists("session:jti-other") and fake.exists("session_full:jti-other")
