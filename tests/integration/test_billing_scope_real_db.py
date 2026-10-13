"""Ownership, rollback, reference disagreement and historical reads on disposable MySQL."""
from __future__ import annotations

import secrets
import json
import time
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
import pymysql
import httpx
from fastapi import FastAPI

from src.Util.db import db_billing
from src.Util.error_handler import AppException, ConflictError
from tests.integration.test_billing_real_db import _real_db

pytestmark = pytest.mark.real_db


def _id(prefix):
    return f"{prefix}-{secrets.token_hex(12)}"


@pytest.fixture
def scopes(real_factory, real_db_conn):
    rows = []
    with real_db_conn.cursor() as cur:
        cur.execute("INSERT IGNORE INTO billing_providers (id, provider_code, display_name) VALUES ('bprov-stripe', 'stripe', 'Stripe')")
    real_db_conn.commit()
    with _real_db():
        for _ in range(2):
            chain = real_factory.create_full_chain()
            group_id = _id("bg")
            db_billing.create_billing_group(id=group_id, billing_group_hash=_id("bgh"), name=group_id,
                                          description=None, owner_id=None, provider="stripe", created_by=None)
            db_billing.attach_project_to_billing_group(id=_id("bgp"), billing_group_id=group_id,
                                                      project_id=chain["project"]["id"], added_by=None)
            rows.append({"user": chain["user"], "project": chain["project"], "group": group_id})
    yield rows
    with real_db_conn.cursor() as cur:
        for row in rows:
            cur.execute("DELETE FROM billing_groups WHERE id = %s", (row["group"],))
    real_db_conn.commit()


def _customer(scope, **overrides):
    digest = secrets.token_bytes(32)
    args = dict(customer_id=_id("bcustrow"), user_id=scope["user"]["id"], billing_group_id=scope["group"],
                provider="stripe", customer_ref=_id("bcust"), provider_customer_id_ciphertext=b"encrypted-test-ref",
                provider_customer_id_hmac=digest, provider_customer_id_fingerprint=digest.hex()[:12],
                provider_ref_key_id="test-key", status="active", safe_metadata={})
    args.update(overrides)
    with _real_db():
        result = db_billing.upsert_customer(**args)
    return {**args, **result}


def _purchase(scope, **overrides):
    args = dict(purchase_id=_id("bpe"), history_id=None, user_id=scope["user"]["id"],
                project_id=scope["project"]["id"], billing_group_id=scope["group"], customer_id=None,
                provider="stripe", purchase_ref=_id("bpur"), checkout_ref=None, status="paid",
                credit_product_code="credits_small", quantity=1, provider_payment_intent_id_ciphertext=None,
                provider_payment_intent_id_hmac=None, provider_payment_intent_id_fingerprint=None,
                provider_charge_id_ciphertext=None, provider_charge_id_hmac=None, provider_charge_id_fingerprint=None,
                provider_ref_key_id=None, observed_at=datetime.now(timezone.utc), sync_source="webhook",
                paid_at=datetime.now(timezone.utc), refunded_at=None, disputed_at=None, stale_after=None,
                reason="test_paid", safe_metadata={})
    args.update(overrides)
    with _real_db():
        result = db_billing.record_purchase_event(**args)
    return {**args, **result}


def _checkout(scope, purchase_ref, **overrides):
    args = dict(intent_id=_id("bci"), user_id=scope["user"]["id"], project_id=scope["project"]["id"],
                billing_group_id=scope["group"], customer_id=None, provider="stripe", checkout_ref=_id("bco"),
                subscription_ref=None, purchase_ref=purchase_ref, intent_type="credit_purchase",
                provider_price_ref_type="price_id", provider_price_ref_hmac=b"p" * 32,
                provider_price_ref_fingerprint=(b"p" * 32).hex()[:12], idempotency_key_hmac=secrets.token_bytes(32),
                canonical_request_hash=secrets.token_bytes(32), plan_code=None, tier_code=None,
                tier_name=None, credit_product_code="credits_small", quantity=1, safe_metadata={})
    args.update(overrides)
    with _real_db():
        result = db_billing.begin_checkout_intent(**args)
    return {**args, **result}


def _subscription(scope, customer, **overrides):
    args = dict(snapshot_id=_id("bss"), history_id=_id("beh"), current_id=_id("bec"),
                subscription_id=_id("bsubrow"), customer_id=customer["customer_id"], user_id=scope["user"]["id"],
                billing_group_id=scope["group"], provider="stripe", subscription_ref=_id("bsub"),
                provider_subscription_id_ciphertext=None, provider_subscription_id_hmac=None,
                provider_subscription_id_fingerprint=None, provider_ref_key_id=None,
                observed_at=datetime.now(timezone.utc), sync_source="webhook", normalized_status="active",
                plan_code="plus", tier_code="plus", tier_name="Plus", cancel_at_period_end=False,
                current_period_end=None, trial_end=None, payload_hash=secrets.token_bytes(32),
                is_complete=True, requires_resync=False, stale_after=None, reason="test_active", safe_metadata={})
    args.update(overrides)
    with _real_db():
        result = db_billing.observe_subscription(**args)
    return {**args, **result}


def _lookup(scope, **overrides):
    args = dict(provider="stripe", billing_group_id=scope["group"], checkout_ref=None,
                subscription_id_hmac=None, payment_intent_id_hmac=None, charge_id_hmac=None,
                customer_id_hmac=None, price_id_hmac=None)
    args.update(overrides)
    with _real_db():
        return db_billing.resolve_event_scope(**args)


def _read(scope, purchase_ref):
    with _real_db():
        return db_billing.get_purchase_status_by_ref(user_hash=scope["user"]["user_hash"],
                    project_hash=scope["project"]["project_hash"], purchase_ref=purchase_ref)


def test_customer_cannot_be_created_for_a_foreign_group(scopes):
    a, b = scopes
    with pytest.raises(ConflictError):
        _customer(b, billing_group_id=a["group"])


@pytest.mark.parametrize("key", ["customer_id", "customer_ref", "provider_customer_id_hmac"])
def test_customer_upsert_rejects_each_foreign_unique_reference(scopes, key):
    a, b = scopes
    customer = _customer(b)
    with pytest.raises(ConflictError):
        _customer(a, **{key: customer[key]})


def test_foreign_subscription_customer_and_ref_are_rejected_without_history(scopes, real_db_conn):
    a, b = scopes
    own_customer, foreign_customer = _customer(a), _customer(b)
    foreign = _subscription(b, foreign_customer)
    with pytest.raises(ConflictError):
        _subscription(a, foreign_customer)
    with pytest.raises(ConflictError):
        _subscription(a, own_customer, subscription_ref=foreign["subscription_ref"])
    # This collision is checked after the subscription insert; it must roll back
    # that insert as well as avoiding snapshot/history writes.
    with pytest.raises(ConflictError):
        _subscription(a, own_customer, snapshot_id=foreign["snapshot_id"])
    with pytest.raises(ConflictError):
        _subscription(a, own_customer, current_id=foreign["current_id"])
    with real_db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM billing_entitlement_history WHERE billing_group_id = %s", (a["group"],))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT COUNT(*) AS n FROM billing_subscription_snapshots WHERE billing_group_id = %s", (a["group"],))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT COUNT(*) AS n FROM billing_subscriptions WHERE billing_group_id = %s", (a["group"],))
        assert cur.fetchone()["n"] == 0


def test_paid_entitlement_cannot_omit_ownership_references(scopes, real_db_conn):
    a, _ = scopes
    with real_db_conn.cursor() as cur:
        with pytest.raises(pymysql.OperationalError, match="owned subscription"):
            cur.execute("""INSERT INTO billing_entitlements_current
                (id, user_id, billing_group_id, provider, status, plan_code)
                VALUES (%s, %s, %s, 'stripe', 'active', 'plus')""",
                (_id("bec"), a["user"]["id"], a["group"]))
    real_db_conn.rollback()


def test_foreign_purchase_project_and_global_ref_are_rejected(scopes):
    a, b = scopes
    original = _purchase(b)
    with pytest.raises(ConflictError):
        _purchase(b, billing_group_id=a["group"])
    with pytest.raises(ConflictError):
        _purchase(a, purchase_ref=original["purchase_ref"], status="refunded")
    assert _read(b, original["purchase_ref"])["status"] == "paid"


def test_lookup_checks_later_references_even_when_checkout_matches(scopes):
    a, b = scopes
    checkout = _checkout(a, _id("bpur"))
    foreign_customer = _customer(b)
    with pytest.raises(ConflictError):
        _lookup(a, checkout_ref=checkout["checkout_ref"], customer_id_hmac=foreign_customer["provider_customer_id_hmac"])
    with pytest.raises(ConflictError):
        _lookup(a, checkout_ref=checkout["checkout_ref"], customer_ref=foreign_customer["customer_ref"])
    assert _lookup(a, checkout_ref=checkout["checkout_ref"])["user_id"] == a["user"]["id"]


def test_known_customer_id_rejects_a_fresh_conflicting_application_ref(scopes):
    a, _ = scopes
    customer = _customer(a)
    with pytest.raises(ConflictError):
        _lookup(a, customer_id_hmac=customer["provider_customer_id_hmac"], customer_ref=_id("bcust"))
    assert _lookup(a, customer_id_hmac=customer["provider_customer_id_hmac"],
                   customer_ref=customer["customer_ref"])["customer_id"] == customer["customer_id"]


def test_known_subscription_rejects_fresh_contradictory_refs(scopes):
    a, _ = scopes
    customer = _customer(a)
    digest = secrets.token_bytes(32)
    subscription = _subscription(a, customer, provider_subscription_id_hmac=digest,
                                provider_subscription_id_ciphertext=b"encrypted-test-ref",
                                provider_subscription_id_fingerprint=digest.hex()[:12], provider_ref_key_id="test-key")
    for conflict in ({"subscription_ref": _id("bsub")}, {"customer_id_hmac": secrets.token_bytes(32)},
                     {"customer_ref": _id("bcust")}):
        with pytest.raises(ConflictError):
            _lookup(a, subscription_id_hmac=digest, **conflict)
    assert _lookup(a, subscription_id_hmac=digest,
                   subscription_ref=subscription["subscription_ref"])["subscription_id"] == subscription["subscription_id"]


def test_known_purchase_rejects_fresh_contradictory_refs(scopes):
    a, _ = scopes
    customer = _customer(a)
    payment_digest, charge_digest = secrets.token_bytes(32), secrets.token_bytes(32)
    purchase = _purchase(a, customer_id=customer["customer_id"],
                         provider_payment_intent_id_hmac=payment_digest,
                         provider_payment_intent_id_ciphertext=b"encrypted-payment-ref",
                         provider_payment_intent_id_fingerprint=payment_digest.hex()[:12],
                         provider_charge_id_hmac=charge_digest, provider_charge_id_ciphertext=b"encrypted-charge-ref",
                         provider_charge_id_fingerprint=charge_digest.hex()[:12], provider_ref_key_id="test-key")
    for conflict in ({"purchase_ref": _id("bpur")}, {"charge_id_hmac": secrets.token_bytes(32)},
                     {"customer_id_hmac": secrets.token_bytes(32)}):
        with pytest.raises(ConflictError):
            _lookup(a, payment_intent_id_hmac=payment_digest, **conflict)
    assert _lookup(a, payment_intent_id_hmac=payment_digest,
                   purchase_ref=purchase["purchase_ref"])["purchase_id"] == purchase["purchase_id"]


@pytest.mark.parametrize("store_customer_on_checkout", [False, True])
def test_checkout_rejects_fresh_customer_id_conflicting_with_its_original_customer(scopes, store_customer_on_checkout):
    a, _ = scopes
    customer = _customer(a)
    checkout = _checkout(a, _id("bpur"),
                         customer_id=customer["customer_id"] if store_customer_on_checkout else None)
    with pytest.raises(ConflictError):
        _lookup(a, checkout_ref=checkout["checkout_ref"], customer_id_hmac=secrets.token_bytes(32))
    assert _lookup(a, checkout_ref=checkout["checkout_ref"],
                   customer_id_hmac=customer["provider_customer_id_hmac"])["customer_id"] == customer["customer_id"]


def test_original_checkout_customer_is_retained_when_another_customer_becomes_active(scopes, real_db_conn):
    a, _ = scopes
    original = _customer(a)
    checkout = _checkout(a, _id("bpur"), customer_id=original["customer_id"])
    with real_db_conn.cursor() as cursor:
        cursor.execute("UPDATE billing_customers SET status='disabled' WHERE id=%s", (original["customer_id"],))
    real_db_conn.commit()
    _customer(a)
    lookup = _lookup(a, checkout_ref=checkout["checkout_ref"],
                    customer_id_hmac=original["provider_customer_id_hmac"])
    assert lookup["customer_id"] == original["customer_id"]


def test_original_checkout_preserves_purchase_after_group_reassignment(scopes):
    a, b = scopes
    ref = _id("bpur")
    checkout = _checkout(a, ref)
    _purchase(a, purchase_ref=ref, checkout_ref=checkout["checkout_ref"])
    with _real_db():
        db_billing.detach_project_from_billing_group(project_id=a["project"]["id"], removed_by=None)
        db_billing.attach_project_to_billing_group(id=_id("bgp"), billing_group_id=b["group"],
                                                  project_id=a["project"]["id"], added_by=None)
    assert _read(a, ref)["status"] == "paid"
    lookup = _lookup(a, checkout_ref=checkout["checkout_ref"])
    assert lookup["historical_checkout_verified"] == 1
    assert lookup["checkout_project_id"] == a["project"]["id"]
    _purchase(a, purchase_ref=ref, checkout_ref=checkout["checkout_ref"], status="refunded")
    assert _read(a, ref)["status"] == "refunded"


def test_unverified_old_group_purchase_is_not_returned_after_reassignment(scopes):
    a, b = scopes
    purchase = _purchase(a)
    with _real_db():
        db_billing.detach_project_from_billing_group(project_id=a["project"]["id"], removed_by=None)
        db_billing.attach_project_to_billing_group(id=_id("bgp"), billing_group_id=b["group"],
                                                  project_id=a["project"]["id"], added_by=None)
    assert _read(a, purchase["purchase_ref"]) is None


def test_readonly_audit_reports_unverified_purchase_without_rewriting_it(scopes, real_db_conn):
    from scripts.migrations.billing_ownership_audit import audit
    a, b = scopes
    purchase = _purchase(a)
    with _real_db():
        db_billing.detach_project_from_billing_group(project_id=a["project"]["id"], removed_by=None)
        db_billing.attach_project_to_billing_group(id=_id("bgp"), billing_group_id=b["group"],
                                                  project_id=a["project"]["id"], added_by=None)
    report = audit(real_db_conn, limit=1000)
    finding = report["checks"]["purchases_without_current_or_original_group"]
    assert purchase["purchase_id"] in finding["sample_local_ids"]
    with real_db_conn.cursor() as cur:
        cur.execute("SELECT status, billing_group_id FROM billing_purchase_events WHERE id = %s", (purchase["purchase_id"],))
        assert cur.fetchone() == {"status": "paid", "billing_group_id": a["group"]}


def test_concurrent_purchase_ref_collision_keeps_one_owner_and_one_history(scopes, real_db_conn):
    barrier, ref = Barrier(2), _id("bpur")
    def attempt(scope):
        barrier.wait(timeout=10)
        try:
            return _purchase(scope, purchase_ref=ref, quantity=1 if scope is scopes[0] else 2)
        except AppException:
            return None
    with _real_db(), ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, scopes))
    assert sum(result is not None for result in results) == 1
    winner = next(result for result in results if result is not None)
    with real_db_conn.cursor() as cur:
        expected = {"user_id": winner["user_id"], "billing_group_id": winner["billing_group_id"], "quantity": winner["quantity"]}
        cur.execute("SELECT user_id, billing_group_id, quantity FROM billing_purchase_events WHERE purchase_ref = %s", (ref,))
        assert cur.fetchall() == [expected]
        cur.execute("SELECT user_id, billing_group_id, quantity FROM billing_purchase_history WHERE purchase_ref = %s", (ref,))
        assert cur.fetchall() == [expected]


@pytest.mark.asyncio
async def test_existing_client_checkout_webhook_and_historical_refund_roundtrip(scopes, monkeypatch):
    """Run with magic_auth_client installed/PYTHONPATH; Stripe network is a stub."""
    client_sdk = pytest.importorskip("magic_auth_client")
    from src.routes import internal_billing, stripe_webhooks
    from src.Util.stripe.config import SUPPORTED_STRIPE_API_VERSION
    from src.Util.stripe.security import compute_stripe_webhook_signature
    a, b = scopes
    token, secret = "test-roundtrip-s2s", "whsec_roundtrip_test"
    for name in ("BILLING_ENABLED", "BILLING_S2S_ENABLED", "BILLING_CHECKOUT_ENABLED",
                 "STRIPE_BILLING_ENABLED", "STRIPE_CHECKOUT_ENABLED", "STRIPE_WEBHOOKS_ENABLED"):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", token)
    monkeypatch.setenv("BILLING_RETURN_URL_ALLOWLIST", "https://app.test")
    monkeypatch.setattr(stripe_webhooks, "_DELIVERY_MEMORY_LEDGER", set())
    monkeypatch.setattr(stripe_webhooks, "_invalidate_user_sessions", lambda *_: None)
    monkeypatch.setattr(stripe_webhooks, "get_billing_group_by_hash",
                        lambda **_: {"id": a["group"], "status": "active", "webhooks_enabled": True})
    monkeypatch.setattr(stripe_webhooks, "get_stripe_account_secrets_for_group", lambda **_: SimpleNamespace(webhook_secret=secret))
    async def no_rate_limit(*_args, **_kwargs):
        return None
    monkeypatch.setattr(internal_billing, "_check_rate_limit", no_rate_limit)
    async def ready_group(_scope):
        return {"status": "active", "credential_status": "active", "checkout_enabled": True,
                "stripe_secret_key_ciphertext": b"test-secret-ciphertext"}
    monkeypatch.setattr(internal_billing, "_billing_group_operational_row", ready_group)

    stripe_params, customer_id = {}, _id("cus")
    class ProviderStub:
        def create_customer(self, **_kwargs):
            return {"id": customer_id}
        def create_checkout_session(self, *, params, **_kwargs):
            stripe_params.update(params)
            return {"id": _id("cs"), "url": "https://checkout.test/session"}
    monkeypatch.setattr(internal_billing, "_group_stripe_client", lambda *_: ProviderStub())
    app = FastAPI()
    app.include_router(internal_billing.router)
    app.include_router(stripe_webhooks.router)
    transport = httpx.ASGITransport(app=app)
    with _real_db():
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            client = client_sdk.MagicAuthClient(client_sdk.MagicAuthConfig(base_url="http://test", user_agent="billing-scope-smoke"), http_client=http)
            checkout = await client.create_billing_checkout(a["user"]["user_hash"], bearer_token=token,
                project_hash=a["project"]["project_hash"].lower(), intent_type="credit_purchase",
                price_ref={"ref_type": "price_id", "value": "price_test_roundtrip"},
                credit_product_code="credits_small", success_url="https://app.test/success", cancel_url="https://app.test/cancel")
            assert checkout.http_status == 202
            metadata = stripe_params["metadata"]
            assert metadata["project_hash"] == a["project"]["project_hash"].lower()
            payment_id = _id("pi")
            async def post_event(event_type, obj):
                payload = {"id": _id("evt"), "object": "event", "type": event_type, "api_version": SUPPORTED_STRIPE_API_VERSION,
                           "data": {"object": obj}}
                raw = json.dumps(payload).encode()
                timestamp = int(time.time())
                signature = compute_stripe_webhook_signature(raw_body=raw, timestamp=timestamp, webhook_secret=secret)
                return await http.post("/webhooks/stripe/smoke-group", content=raw,
                    headers={"Stripe-Signature": f"t={timestamp},v1={signature}"})
            paid = {"id": _id("cs"), "object": "checkout.session", "mode": "payment", "status": "complete",
                    "payment_status": "paid", "customer": customer_id, "payment_intent": payment_id, "metadata": metadata}
            foreign = {**paid, "metadata": {**metadata, "user_hash": b["user"]["user_hash"], "project_hash": b["project"]["project_hash"]}}
            assert (await post_event("checkout.session.completed", foreign)).status_code == 403
            assert (await post_event("checkout.session.completed", paid)).status_code == 200
            read = await client.get_billing_purchase(a["user"]["user_hash"], checkout.purchase_ref,
                    project_hash=a["project"]["project_hash"], bearer_token=token)
            assert read.purchase.status == "paid" and read.purchase.quantity == 1
            db_billing.detach_project_from_billing_group(project_id=a["project"]["id"], removed_by=None)
            db_billing.attach_project_to_billing_group(id=_id("bgp"), billing_group_id=b["group"], project_id=a["project"]["id"], added_by=None)
            refund = {"id": _id("ch"), "object": "charge", "customer": customer_id, "payment_intent": payment_id,
                      "amount": 100, "amount_refunded": 100, "refunded": True, "metadata": metadata}
            assert (await post_event("charge.refunded", refund)).status_code == 200
            read = await client.get_billing_purchase(a["user"]["user_hash"], checkout.purchase_ref,
                    project_hash=a["project"]["project_hash"], bearer_token=token)
            assert read.purchase.status == "refunded"
