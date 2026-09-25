from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import fakeredis
import pytest

from src.Util.billing import sync as billing_sync
from src.Util.billing.config import load_billing_config
from src.Util.billing.security import encrypt_provider_ref, hmac_provider_ref
from src.Util.billing.provider import BillingSyncJob, BillingSyncResult
from src.Util.cache_manager import cache_manager
from src.Util.stripe import sync as stripe_sync
from src.workers import billing_sync_worker


@pytest.mark.asyncio
async def test_worker_uses_billing_group_client_for_stripe_sync(monkeypatch):
    captured: dict[str, object] = {}
    fake_client = object()

    monkeypatch.setattr(
        billing_sync_worker,
        "get_stripe_client_for_group",
        lambda **kwargs: captured.setdefault("client_kwargs", kwargs) and fake_client,
    )

    def _source_of_truth_resync(**kwargs):
        captured["sync_client"] = kwargs["client"]
        return BillingSyncResult(provider="stripe", job_id=kwargs["job"].job_id, status="completed")

    monkeypatch.setattr(billing_sync_worker.stripe_source_sync, "source_of_truth_resync", _source_of_truth_resync)

    worker = billing_sync_worker.BillingSyncWorker(
        worker_id="test-worker",
        config=SimpleNamespace(sync_enabled=True, decryption_keys_by_id={"key-1": "secret"}),
        stripe_config=SimpleNamespace(sync_enabled=True, api_version="2026-05-27.dahlia"),
        db=SimpleNamespace(),
    )
    job = billing_sync.ClaimedBillingSyncJob(
        job_id="bsync-1",
        provider="stripe",
        job_type="subscription",
        user_id="usr-1",
        billing_group_id="bg-1",
        subscription_id="bsub-1",
    )

    result = await worker._dispatch_stripe_sync(job=job, row={})

    assert result.status == "completed"
    assert captured["sync_client"] is fake_client
    assert captured["client_kwargs"]["billing_group_id"] == "bg-1"
    assert captured["client_kwargs"]["decryption_keys_by_id"] == {"key-1": "secret"}


def test_source_sync_missing_operational_ref_is_non_retryable():
    result = stripe_sync.source_of_truth_resync(
        job=BillingSyncJob(job_id="bsync-2", provider="stripe", job_type="subscription", billing_group_id="bg-1"),
        client=object(),
        operational_refs={},
        decryption_keys_by_id={},
    )

    assert result.status == "failed"
    assert result.retryable is False
    assert result.reason == "missing_operational_ref"


def test_cli_passes_a_stable_worker_id_for_the_heartbeat(monkeypatch):
    created: list[dict] = []

    class _Worker:
        def __init__(self, **kwargs):
            created.append(kwargs)

        def run_forever(self):
            return None

    monkeypatch.setattr(billing_sync_worker, "BillingSyncWorker", _Worker)

    assert billing_sync_worker.main(["--worker-id", "container-host-billing"]) == 0
    assert created == [{"worker_id": "container-host-billing"}]


# ─── Resync writes the fetched Stripe object back ────────────────────────────
# The worker used to fetch the object and complete the job without writing anything, and a
# resync requested through the S2S route carried no ref to fetch, so it ended `failed`.

SUBSCRIPTION_METADATA = {
    "api_auth_checkout_ref": "bco-059317deacb42c362029c60b09420c93",
    "api_auth_subscription_ref": "bsub-b2dbca0a1198e8051126c02b578465c4",
    "consumer_plan_code": "magic_worlds_plus",
    "consumer_tier_code": "artisan",
}


def _config():
    return dataclasses.replace(load_billing_config(), sync_enabled=True)


def _encrypted(raw_id: str, config) -> tuple[bytes, str]:
    ref = encrypt_provider_ref(
        raw_ref=raw_id,
        key=config.provider_ref_encryption_key,
        key_id=config.provider_ref_encryption_key_id,
        provider="stripe",
    )
    return ref.ciphertext, ref.key_id


def _subscription(sub_id: str, status: str, *, created: int, metadata: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "id": sub_id,
        "object": "subscription",
        "status": status,
        "created": created,
        "customer": "cus_test_fixture_project_001",
        "cancel_at_period_end": False,
        "trial_end": None,
        "metadata": dict(metadata or {}),
        "items": {"data": [{"current_period_end": 1896134400, "price": {"id": "price_test_fixture_plus", "lookup_key": "plus_monthly"}}]},
    }


class _FakeStripe:
    def __init__(self, *, subscriptions=(), subscription=None, payment_intent=None, charge=None):
        self._subscriptions = list(subscriptions)
        self._subscription = subscription
        self._payment_intent = payment_intent
        self._charge = charge
        self.calls: list[tuple[str, str]] = []

    def list_customer_subscriptions(self, customer_id: str):
        self.calls.append(("list_customer_subscriptions", customer_id))
        return list(self._subscriptions)

    def retrieve_subscription(self, subscription_id: str):
        self.calls.append(("retrieve_subscription", subscription_id))
        return dict(self._subscription)

    def retrieve_payment_intent(self, payment_intent_id: str):
        self.calls.append(("retrieve_payment_intent", payment_intent_id))
        return dict(self._payment_intent)

    def retrieve_charge(self, charge_id: str):
        self.calls.append(("retrieve_charge", charge_id))
        return dict(self._charge)


class _FakeDb:
    def __init__(self, *, context: dict[str, Any] | None = None, lookup: dict[str, Any] | None = None, fail_writes: bool = False):
        self.context = context or {}
        self.lookup = lookup
        self.fail_writes = fail_writes
        self.context_calls: list[dict[str, Any]] = []
        self.lookup_calls: list[dict[str, Any]] = []
        self.observed: list[dict[str, Any]] = []
        self.purchases: list[dict[str, Any]] = []
        self.completed: list[dict[str, Any]] = []

    def get_sync_context(self, **kwargs):
        self.context_calls.append(kwargs)
        return dict(self.context)

    def resolve_event_scope(self, **kwargs):
        self.lookup_calls.append(kwargs)
        return dict(self.lookup) if self.lookup else None

    def observe_subscription(self, **kwargs):
        if self.fail_writes:
            raise RuntimeError("db down")
        self.observed.append(kwargs)
        return {"subscription_id": kwargs["subscription_id"]}

    def record_purchase_event(self, **kwargs):
        self.purchases.append(kwargs)
        return {"purchase_id": kwargs["purchase_id"]}

    def complete_sync_job(self, **kwargs):
        self.completed.append(kwargs)
        return {"job_id": kwargs["job_id"], "job_status": kwargs["status"]}


def _build_worker(*, client, db, config):
    return billing_sync_worker.BillingSyncWorker(
        worker_id="test-worker",
        client=client,
        db=db,
        redis=SimpleNamespace(),
        config=config,
        stripe_config=SimpleNamespace(sync_enabled=True, api_version="2026-05-27.dahlia"),
    )


def _worker(monkeypatch, *, client, db, config):
    invalidated: list[str] = []
    monkeypatch.setattr(
        billing_sync_worker.BillingSyncWorker,
        "_invalidate_user_sessions",
        staticmethod(lambda user_id: invalidated.append(user_id)),
    )
    return _build_worker(client=client, db=db, config=config), invalidated


def _job_row(job_type: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": "bsync-1",
        "provider": "stripe",
        "job_type": job_type,
        "user_id": "usr-1",
        "project_id": "prj-1",
        "billing_group_id": "bg-1",
        "attempts": 1,
        "max_attempts": 8,
        "sanitized_metadata": {"route": "billing_resync", "billing_group_id": "bg-1"},
        **extra,
    }


@pytest.mark.asyncio
async def test_user_level_resync_lists_the_customers_subscriptions_and_writes_the_current_one(monkeypatch):
    config = _config()
    customer_ciphertext, key_id = _encrypted("cus_test_fixture_project_001", config)
    db = _FakeDb(context={"user_id": "usr-1", "billing_group_id": "bg-1", "customer_id": "bcustrow-1", "customer_ref": "bcust-1",
                          "provider_customer_id_ciphertext": customer_ciphertext, "customer_provider_ref_key_id": key_id})
    client = _FakeStripe(
        subscriptions=[
            _subscription("sub_test_old", "canceled", created=100),
            _subscription("sub_test_current", "active", created=200, metadata=SUBSCRIPTION_METADATA),
        ]
    )
    worker, invalidated = _worker(monkeypatch, client=client, db=db, config=config)

    item = await worker._process_claimed_job(_job_row("webhook_resync"))

    assert item.status == "completed", item
    assert item.reason == "facts_written"
    assert db.context_calls == [
        {"provider": "stripe", "user_id": "usr-1", "billing_group_id": "bg-1", "subscription_id": None, "purchase_id": None}
    ]
    assert client.calls == [("list_customer_subscriptions", "cus_test_fixture_project_001")]
    [observed] = db.observed
    assert observed["normalized_status"] == "active"
    assert observed["sync_source"] == "api_pull"
    assert observed["user_id"] == "usr-1" and observed["billing_group_id"] == "bg-1"
    assert observed["customer_id"] == "bcustrow-1"
    assert observed["subscription_ref"] == SUBSCRIPTION_METADATA["api_auth_subscription_ref"]
    assert observed["plan_code"] == "magic_worlds_plus" and observed["tier_code"] == "artisan"
    assert observed["current_period_end"] == datetime(2030, 2, 1, tzinfo=timezone.utc)
    assert observed["provider_subscription_id_hmac"] == hmac_provider_ref(
        provider="stripe", kind="subscription_id", raw_id="sub_test_current", secret=config.id_hmac_secret
    )
    assert db.lookup_calls[0]["subscription_id_hmac"] == observed["provider_subscription_id_hmac"]
    assert db.completed == [{"job_id": "bsync-1", "status": "completed", "retry_after_seconds": None, "last_error_redacted": None}]
    assert invalidated == ["usr-1"]


@pytest.mark.asyncio
async def test_subscription_resync_keeps_access_sessions_and_drops_cached_validation(monkeypatch):
    # The worker used to delete the user's session:* records too, signing them out on every resync.
    fake = fakeredis.FakeStrictRedis()
    monkeypatch.setattr(cache_manager, "redis", fake)
    for jti, user_id in (("jti-own", "usr-1"), ("jti-other", "usr-2")):
        fake.set(f"session:{jti}", json.dumps({"user_id": user_id}))
        fake.set(f"session_full:{jti}", json.dumps({"user_id": user_id}))
    config = _config()
    customer_ciphertext, key_id = _encrypted("cus_test_fixture_project_001", config)
    db = _FakeDb(context={"user_id": "usr-1", "billing_group_id": "bg-1", "customer_id": "bcustrow-1", "customer_ref": "bcust-1",
                          "provider_customer_id_ciphertext": customer_ciphertext, "customer_provider_ref_key_id": key_id})
    client = _FakeStripe(subscriptions=[_subscription("sub_test_current", "active", created=200, metadata=SUBSCRIPTION_METADATA)])
    worker = _build_worker(client=client, db=db, config=config)

    item = await worker._process_claimed_job(_job_row("webhook_resync"))

    assert item.status == "completed", item
    assert [row["normalized_status"] for row in db.observed] == ["active"]
    assert fake.exists("session:jti-own")  # still signed in
    assert not fake.exists("session_full:jti-own")  # plan recomputed on the next validate
    assert fake.exists("session:jti-other") and fake.exists("session_full:jti-other")


@pytest.mark.asyncio
async def test_subscription_job_writes_back_under_the_stored_row_and_labels(monkeypatch):
    config = _config()
    subscription_ciphertext, key_id = _encrypted("sub_test_legacy", config)
    db = _FakeDb(
        context={
            "user_id": "usr-1",
            "billing_group_id": "bg-1",
            "customer_id": "bcustrow-1",
            "subscription_id": "bsubrow-1",
            "subscription_ref": "bsub-legacy",
            "subscription_plan_code": "plus",
            "subscription_tier_code": "gold",
            "provider_subscription_id_ciphertext": subscription_ciphertext,
            "subscription_provider_ref_key_id": key_id,
        }
    )
    # Created before Checkout copied its metadata: the subscription carries none.
    client = _FakeStripe(subscription=_subscription("sub_test_legacy", "past_due", created=100))
    worker, _ = _worker(monkeypatch, client=client, db=db, config=config)

    item = await worker._process_claimed_job(_job_row("subscription", subscription_id="bsubrow-1"))

    assert item.status == "completed", item
    assert client.calls == [("retrieve_subscription", "sub_test_legacy")]
    [observed] = db.observed
    assert observed["subscription_id"] == "bsubrow-1"
    assert observed["subscription_ref"] == "bsub-legacy"
    assert observed["plan_code"] == "plus" and observed["tier_code"] == "gold"
    assert observed["normalized_status"] == "past_due"


@pytest.mark.asyncio
async def test_purchase_job_reads_the_latest_charge_and_records_the_refund(monkeypatch):
    config = _config()
    payment_intent_ciphertext, key_id = _encrypted("pi_test_fixture_credit_001", config)
    db = _FakeDb(
        context={
            "user_id": "usr-1",
            "billing_group_id": "bg-1",
            "project_id": "prj-1",
            "customer_id": "bcustrow-1",
            "purchase_id": "bpe-1",
            "purchase_ref": "bpur-c91a765a69097e3dedb5b55f6b8daf6c",
            "purchase_status": "paid",
            "credit_product_code": "credits_small",
            "quantity": 1,
            "provider_payment_intent_id_ciphertext": payment_intent_ciphertext,
            "purchase_provider_ref_key_id": key_id,
        }
    )
    client = _FakeStripe(
        payment_intent={"id": "pi_test_fixture_credit_001", "status": "succeeded", "latest_charge": "ch_test_fixture_credit_001"},
        charge={
            "id": "ch_test_fixture_credit_001",
            "payment_intent": "pi_test_fixture_credit_001",
            "status": "succeeded",
            "paid": True,
            "amount": 500,
            "amount_refunded": 500,
            "refunded": True,
            "created": 1893456000,
        },
    )
    worker, _ = _worker(monkeypatch, client=client, db=db, config=config)

    item = await worker._process_claimed_job(_job_row("purchase", purchase_id="bpe-1"))

    assert item.status == "completed", item
    assert client.calls == [("retrieve_payment_intent", "pi_test_fixture_credit_001"), ("retrieve_charge", "ch_test_fixture_credit_001")]
    [purchase] = db.purchases
    assert purchase["status"] == "refunded"
    assert purchase["purchase_id"] == "bpe-1"
    assert purchase["purchase_ref"] == "bpur-c91a765a69097e3dedb5b55f6b8daf6c"
    assert purchase["project_id"] == "prj-1" and purchase["credit_product_code"] == "credits_small" and purchase["quantity"] == 1
    assert purchase["sync_source"] == "api_pull"
    assert purchase["paid_at"] == datetime.fromtimestamp(1893456000, tz=timezone.utc)
    assert purchase["refunded_at"] is not None
    assert isinstance(purchase["provider_charge_id_hmac"], bytes)


@pytest.mark.asyncio
async def test_user_level_resync_without_any_stripe_ref_completes_as_a_noop(monkeypatch):
    db = _FakeDb(context={"user_id": "usr-1", "billing_group_id": "bg-1"})
    client = _FakeStripe()
    worker, _ = _worker(monkeypatch, client=client, db=db, config=_config())

    item = await worker._process_claimed_job(_job_row("webhook_resync"))

    assert item.status == "completed"
    assert item.reason == "no_provider_refs"
    assert client.calls == [] and db.observed == []
    assert db.completed == [
        {"job_id": "bsync-1", "status": "completed", "retry_after_seconds": None, "last_error_redacted": "no_provider_refs"}
    ]


@pytest.mark.asyncio
async def test_failed_write_back_retries_the_job(monkeypatch):
    config = _config()
    customer_ciphertext, key_id = _encrypted("cus_test_fixture_project_001", config)
    db = _FakeDb(
        context={"user_id": "usr-1", "billing_group_id": "bg-1", "customer_id": "bcustrow-1",
                 "provider_customer_id_ciphertext": customer_ciphertext, "customer_provider_ref_key_id": key_id},
        fail_writes=True,
    )
    client = _FakeStripe(subscriptions=[_subscription("sub_test_current", "active", created=200, metadata=SUBSCRIPTION_METADATA)])
    worker, _ = _worker(monkeypatch, client=client, db=db, config=config)

    item = await worker._process_claimed_job(_job_row("webhook_resync"))

    assert item.status == "retry"
    assert db.completed[0]["status"] == "retry"


@pytest.mark.asyncio
async def test_subscription_owned_by_another_user_is_not_written(monkeypatch):
    config = _config()
    customer_ciphertext, key_id = _encrypted("cus_test_fixture_project_001", config)
    db = _FakeDb(
        context={"user_id": "usr-1", "billing_group_id": "bg-1", "customer_id": "bcustrow-1",
                 "provider_customer_id_ciphertext": customer_ciphertext, "customer_provider_ref_key_id": key_id},
        lookup={"matched_by": "subscription", "user_id": "usr-other", "billing_group_id": "bg-1", "subscription_id": "bsubrow-9"},
    )
    client = _FakeStripe(subscriptions=[_subscription("sub_test_current", "active", created=200)])
    worker, _ = _worker(monkeypatch, client=client, db=db, config=config)

    item = await worker._process_claimed_job(_job_row("webhook_resync"))

    assert item.status == "failed"
    assert item.reason == "provider_object_owned_by_another_user"
    assert db.observed == []


def test_current_subscription_prefers_live_over_ended_then_newest():
    subscriptions = [
        {"id": "a", "status": "canceled", "created": 300},
        {"id": "b", "status": "past_due", "created": 100},
        {"id": "c", "status": "active", "created": 50},
        {"id": "d", "status": "active", "created": 60},
    ]

    assert stripe_sync.select_current_subscription(subscriptions)["id"] == "d"
    assert stripe_sync.select_current_subscription([{"id": "x", "status": "canceled", "created": 1}])["id"] == "x"
    assert stripe_sync.select_current_subscription([]) is None
