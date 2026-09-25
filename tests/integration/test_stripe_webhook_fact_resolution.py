"""Stripe events after Checkout reach the billing facts.

Checkout used to put `user_hash`, `project_hash`, and the api.auth refs only on the Checkout
Session, with `project_hash` masked to ***FILTERED***. The webhook resolved every event from
its object's own metadata, so subscription, invoice, refund, and dispute events wrote no
fact. The fixtures are shaped as Stripe sends them now that Checkout copies its metadata onto
the Subscription / PaymentIntent (API 2026-05-27.dahlia): invoices carry it under
`parent.subscription_details`, disputes carry none.
"""

from __future__ import annotations

import copy
import importlib
import json
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.Util.billing.config import load_billing_config
from src.Util.billing.security import hmac_provider_ref
from src.Util.stripe.security import compute_stripe_webhook_signature


ROOT = Path(__file__).resolve().parents[2]
WEBHOOK_ROOT = ROOT / "tests" / "fixtures" / "stripe" / "webhooks"
WEBHOOK_PATH = "/webhooks/stripe"

USER_HASH = "usr-5b8c7c1e-7f3a-4d2b-9c61-0a1b2c3d4e5f"
PROJECT_HASH = "7CCC926F2F5FEB07C973606EB2DF02BC3607C9C5B80A104DF5AAC9A1991F6173"
CUSTOMER_REF = "bcust-de7711233f9b877f28ac38c9b1495e1a"
SUB_CHECKOUT_REF = "bco-059317deacb42c362029c60b09420c93"
SUBSCRIPTION_REF = "bsub-b2dbca0a1198e8051126c02b578465c4"
PAY_CHECKOUT_REF = "bco-0858edce6733a894b5544b81956d8e92"
PURCHASE_REF = "bpur-c91a765a69097e3dedb5b55f6b8daf6c"
SCOPE = {"user_id": "usr-1", "project_id": "prj-1", "billing_group_id": "bg-1", "user_hash": USER_HASH, "project_hash": PROJECT_HASH}


def _route_module():
    return importlib.import_module("src.routes.stripe_webhooks")


@asynccontextmanager
async def _client():
    app = FastAPI(title="Stripe webhook fact resolution test app")
    app.include_router(_route_module().router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _fixture(filename: str) -> tuple[bytes, str]:
    manifest = json.loads((WEBHOOK_ROOT / "signature_headers.json").read_text(encoding="utf-8"))
    return (WEBHOOK_ROOT / filename).read_bytes(), manifest["headers"][filename]["stripe_signature"]


def _signed(payload: dict[str, Any]) -> tuple[bytes, str]:
    """Sign a modified fixture payload with the configured webhook secret, as of now."""

    raw = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    timestamp = int(time.time())
    secret = str(_route_module().load_stripe_config().webhook_secret)
    return raw, f"t={timestamp},v1={compute_stripe_webhook_signature(raw_body=raw, timestamp=timestamp, webhook_secret=secret)}"


def _payload(filename: str) -> dict[str, Any]:
    return copy.deepcopy(json.loads((WEBHOOK_ROOT / filename).read_text(encoding="utf-8")))


def _hmac(raw_id: str, kind: str) -> bytes:
    return hmac_provider_ref(provider="stripe", kind=kind, raw_id=raw_id, secret=load_billing_config().id_hmac_secret)


class _Seams:
    """Captures every fact the route writes; no DB, Redis, or Stripe."""

    def __init__(self, monkeypatch, *, metadata_scope: dict[str, Any] | None = None, lookup: dict[str, Any] | None = None):
        module = _route_module()
        monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
        monkeypatch.setenv("BILLING_ENABLED", "true")
        monkeypatch.setattr(module, "_DELIVERY_MEMORY_LEDGER", set())
        monkeypatch.setattr(module, "record_webhook_delivery", lambda **_: {"delivery_status": "accepted"})
        monkeypatch.setattr(module, "_invalidate_user_sessions", lambda *_a, **_k: None)
        self.scope_calls: list[dict[str, Any]] = []
        self.lookup_calls: list[dict[str, Any]] = []
        self.customers: list[dict[str, Any]] = []
        self.observed: list[dict[str, Any]] = []
        self.purchases: list[dict[str, Any]] = []
        self.jobs: list[dict[str, Any]] = []

        def _resolve_scope(**kwargs):
            self.scope_calls.append(kwargs)
            return dict(metadata_scope) if metadata_scope else None

        def _lookup(**kwargs):
            self.lookup_calls.append(kwargs)
            return dict(lookup) if lookup else None

        def _upsert_customer(**kwargs):
            self.customers.append(kwargs)
            return {"customer_id": "bcustrow-1", "customer_ref": kwargs["customer_ref"]}

        def _observe(**kwargs):
            self.observed.append(kwargs)
            return {"subscription_id": kwargs["subscription_id"], "subscription_ref": kwargs["subscription_ref"]}

        def _record_purchase(**kwargs):
            self.purchases.append(kwargs)
            return {"purchase_id": kwargs["purchase_id"], "purchase_ref": kwargs["purchase_ref"]}

        monkeypatch.setattr(module, "resolve_user_billing_group", _resolve_scope)
        monkeypatch.setattr(module, "resolve_event_scope", _lookup)
        monkeypatch.setattr(module, "upsert_customer", _upsert_customer)
        monkeypatch.setattr(module, "observe_subscription", _observe)
        monkeypatch.setattr(module, "record_purchase_event", _record_purchase)
        monkeypatch.setattr(module, "enqueue_sync_job", lambda **kwargs: self.jobs.append(kwargs) or {"job_id": kwargs["job_id"]})

    async def post(self, raw: bytes, signature: str) -> httpx.Response:
        async with _client() as client:
            return await client.post(
                WEBHOOK_PATH,
                content=raw,
                headers={"Content-Type": "application/json", "User-Agent": "stripe-fact-test", "Stripe-Signature": signature},
            )


@pytest.mark.asyncio
async def test_subscription_update_after_checkout_writes_the_fact_from_subscription_metadata(monkeypatch):
    seams = _Seams(monkeypatch, metadata_scope=SCOPE)

    response = await seams.post(*_fixture("customer_subscription_updated.json"))

    assert response.status_code == 200
    assert response.json() == {"success": True, "status": "accepted"}
    assert seams.scope_calls == [{"user_hash": USER_HASH, "project_hash": PROJECT_HASH}]
    assert seams.customers[0]["customer_ref"] == CUSTOMER_REF
    [observed] = seams.observed
    assert observed["user_id"] == "usr-1" and observed["billing_group_id"] == "bg-1"
    assert observed["customer_id"] == "bcustrow-1"
    assert observed["subscription_ref"] == SUBSCRIPTION_REF
    assert observed["normalized_status"] == "active"
    assert observed["plan_code"] == "magic_worlds_plus" and observed["tier_code"] == "artisan"
    assert observed["current_period_end"] == datetime(2030, 2, 1, tzinfo=timezone.utc)
    assert observed["provider_subscription_id_hmac"] == _hmac("sub_test_fixture_magic_worlds_001", "subscription_id")
    assert seams.jobs == []


@pytest.mark.asyncio
async def test_invoice_event_resolves_through_the_invoice_parent_subscription(monkeypatch):
    seams = _Seams(monkeypatch, metadata_scope=SCOPE)

    response = await seams.post(*_fixture("invoice_paid.json"))

    assert response.status_code == 200
    assert seams.scope_calls == [{"user_hash": USER_HASH, "project_hash": PROJECT_HASH}]
    [observed] = seams.observed
    assert observed["subscription_ref"] == SUBSCRIPTION_REF
    assert observed["normalized_status"] == "active"
    assert observed["provider_subscription_id_hmac"] == _hmac("sub_test_fixture_magic_worlds_001", "subscription_id")
    # An invoice carries no period dates; the procedure keeps the stored ones.
    assert observed["current_period_end"] is None


@pytest.mark.asyncio
async def test_refund_after_credit_checkout_updates_the_same_purchase(monkeypatch):
    seams = _Seams(monkeypatch, metadata_scope=SCOPE)

    response = await seams.post(*_fixture("charge_refunded.json"))

    assert response.status_code == 200
    [purchase] = seams.purchases
    assert purchase["purchase_ref"] == PURCHASE_REF
    assert purchase["checkout_ref"] == PAY_CHECKOUT_REF
    assert purchase["status"] == "refunded"
    assert purchase["credit_product_code"] == "credits_small"
    assert purchase["project_id"] == "prj-1"


@pytest.mark.asyncio
async def test_dispute_without_metadata_resolves_through_the_stored_purchase(monkeypatch):
    lookup = {
        "matched_by": "purchase",
        "user_id": "usr-1",
        "project_id": "prj-1",
        "billing_group_id": "bg-1",
        "customer_id": "bcustrow-1",
        "purchase_id": "bpe-1",
        "purchase_ref": PURCHASE_REF,
        "purchase_status": "paid",
        "checkout_ref": PAY_CHECKOUT_REF,
        "credit_product_code": "credits_small",
        "quantity": 2,
    }
    seams = _Seams(monkeypatch, lookup=lookup)

    response = await seams.post(*_fixture("charge_dispute_created.json"))

    assert response.status_code == 200
    assert seams.scope_calls == [], "a dispute has no user/project metadata to resolve"
    [lookup_call] = seams.lookup_calls
    assert lookup_call["payment_intent_id_hmac"] == _hmac("pi_test_fixture_credit_001", "payment_intent_id")
    assert lookup_call["charge_id_hmac"] == _hmac("ch_test_fixture_credit_001", "charge_id")
    assert all(value is None or isinstance(value, bytes) for key, value in lookup_call.items() if key.endswith("_hmac"))
    [purchase] = seams.purchases
    assert purchase["purchase_id"] == "bpe-1"
    assert purchase["purchase_ref"] == PURCHASE_REF
    assert purchase["status"] == "disputed"
    assert purchase["user_id"] == "usr-1" and purchase["project_id"] == "prj-1" and purchase["billing_group_id"] == "bg-1"
    assert purchase["customer_id"] == "bcustrow-1"
    assert purchase["checkout_ref"] == PAY_CHECKOUT_REF
    assert purchase["credit_product_code"] == "credits_small" and purchase["quantity"] == 2


@pytest.mark.asyncio
async def test_subscription_created_before_checkout_copied_metadata_resolves_through_its_customer(monkeypatch):
    lookup = {
        "matched_by": "customer",
        "user_id": "usr-1",
        "billing_group_id": "bg-1",
        "customer_id": "bcustrow-1",
        "customer_ref": CUSTOMER_REF,
        "catalog_plan_code": "magic_worlds_plus",
        "catalog_tier_code": "artisan",
        "catalog_tier_name": "Artisan",
    }
    seams = _Seams(monkeypatch, lookup=lookup)
    payload = _payload("customer_subscription_updated.json")
    payload["data"]["object"]["metadata"] = {}

    response = await seams.post(*_signed(payload))

    assert response.status_code == 200
    [lookup_call] = seams.lookup_calls
    assert lookup_call["customer_id_hmac"] == _hmac("cus_test_fixture_project_001", "customer_id")
    assert lookup_call["price_id_hmac"] == _hmac("price_test_fixture_magic_worlds_plus_monthly", "price_id")
    [observed] = seams.observed
    assert observed["user_id"] == "usr-1" and observed["billing_group_id"] == "bg-1"
    assert observed["plan_code"] == "magic_worlds_plus"
    assert observed["tier_code"] == "artisan" and observed["tier_name"] == "Artisan"
    assert observed["subscription_ref"].startswith("bsub-")


@pytest.mark.asyncio
async def test_checkout_replayed_from_before_the_fix_resolves_by_its_checkout_ref(monkeypatch):
    """Sessions created before the fix carry `project_hash: ***FILTERED***`."""

    lookup = {
        "matched_by": "checkout_ref",
        "user_id": "usr-1",
        "project_id": "prj-1",
        "billing_group_id": "bg-1",
        "customer_id": "bcustrow-1",
        "subscription_ref": SUBSCRIPTION_REF,
        "checkout_ref": SUB_CHECKOUT_REF,
        "intent_type": "subscription",
        "plan_code": "magic_worlds_plus",
        "tier_code": "artisan",
    }
    seams = _Seams(monkeypatch, lookup=lookup)
    payload = _payload("checkout_session_completed_subscription.json")
    payload["data"]["object"]["metadata"]["project_hash"] = "***FILTERED***"

    response = await seams.post(*_signed(payload))

    assert response.status_code == 200
    assert seams.lookup_calls[0]["checkout_ref"] == SUB_CHECKOUT_REF
    [observed] = seams.observed
    assert observed["user_id"] == "usr-1"
    assert observed["subscription_ref"] == SUBSCRIPTION_REF
    assert observed["normalized_status"] == "pending"


@pytest.mark.asyncio
async def test_late_checkout_completion_does_not_downgrade_an_active_subscription(monkeypatch):
    lookup = {
        "matched_by": "checkout_ref",
        "user_id": "usr-1",
        "project_id": "prj-1",
        "billing_group_id": "bg-1",
        "customer_id": "bcustrow-1",
        "subscription_id": "bsubrow-1",
        "subscription_ref": SUBSCRIPTION_REF,
        "subscription_status": "active",
    }
    seams = _Seams(monkeypatch, metadata_scope=SCOPE, lookup=lookup)

    response = await seams.post(*_fixture("checkout_session_completed_subscription.json"))

    assert response.status_code == 200
    [observed] = seams.observed
    assert observed["subscription_id"] == "bsubrow-1"
    assert observed["normalized_status"] == "active"


@pytest.mark.asyncio
async def test_event_that_resolves_to_no_user_writes_and_queues_nothing(monkeypatch):
    seams = _Seams(monkeypatch)

    response = await seams.post(*_fixture("charge_dispute_created.json"))

    assert response.status_code == 200
    assert seams.observed == [] and seams.purchases == [] and seams.customers == []
    assert seams.jobs == [], "a job without a user or group can only end failed"


@pytest.mark.asyncio
async def test_allowed_webhook_events_setting_narrows_what_is_processed(monkeypatch):
    seams = _Seams(monkeypatch, metadata_scope=SCOPE)
    monkeypatch.setenv("STRIPE_ALLOWED_WEBHOOK_EVENTS", "checkout.session.completed,invoice.paid")

    def _classifier_must_not_run(**_kwargs):
        raise AssertionError("an event type outside STRIPE_ALLOWED_WEBHOOK_EVENTS must not be classified")

    monkeypatch.setattr(_route_module(), "classify_stripe_event", _classifier_must_not_run)

    response = await seams.post(*_fixture("customer_subscription_updated.json"))

    assert response.status_code == 200
    assert response.json() == {"success": True, "status": "ignored_noop"}
    assert seams.observed == []
