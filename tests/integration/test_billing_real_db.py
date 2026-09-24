"""Billing group reads and the S2S purchase lookup against real MySQL.

The static checks prove the procedures name the right columns; these prove the procedures run
and return them, and that the purchase lookup is scoped to the user and the project.

Needs the disposable MySQL from ``docker-compose.test.yml``; skipped otherwise.
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from unittest.mock import patch

import httpx
import pymysql
import pytest
from fastapi import FastAPI

from src.Util.db import db_billing
from tests.integration.conftest import _REAL_DB_CONFIG


pytestmark = pytest.mark.real_db

S2S_TOKEN = "test-billing-s2s-bearer-token-not-real"
FORBIDDEN_PURCHASE_KEYS = {"customer_id", "checkout_ref", "safe_metadata", "user_id", "project_id", "billing_group_id"}


def _tuple_connection():
    cfg = {**_REAL_DB_CONFIG}
    cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


@contextmanager
def _real_db():
    with patch("src.Util.db.db_billing.get_connection", _tuple_connection):
        yield


@pytest.fixture
def group(real_db_conn):
    with real_db_conn.cursor() as cursor:
        cursor.execute(
            "INSERT IGNORE INTO billing_providers (id, provider_code, display_name) VALUES ('bprov-stripe', 'stripe', 'Stripe')"
        )
    real_db_conn.commit()
    group_id = f"bg-{secrets.token_hex(12)}"
    group_hash = secrets.token_hex(16).upper()
    with _real_db():
        db_billing.create_billing_group(
            id=group_id, billing_group_hash=group_hash, name="Real DB group", description=None,
            owner_id=None, provider="stripe", created_by=None,
        )
    yield {"id": group_id, "hash": group_hash}
    # Purchase history refuses direct deletes (retained indefinitely); the group delete
    # cascades to it, and FK cascades do not fire that trigger.
    with real_db_conn.cursor() as cursor:
        cursor.execute("DELETE FROM billing_groups WHERE id = %s", (group_id,))
    real_db_conn.commit()


def test_group_get_and_list_return_capabilities_webhook_presence_and_catalog_sync(group):
    from src.routes.admin_billing import _group_info

    with _real_db():
        db_billing.set_billing_group_credentials(
            id=group["id"], stripe_account_label="acct", stripe_account_fingerprint="acctfp000001",
            stripe_secret_key_ciphertext=b"ct-secret", stripe_secret_key_hmac=b"s" * 32,
            stripe_secret_key_fingerprint="skfp00000001", stripe_webhook_secret_ciphertext=b"ct-webhook",
            stripe_webhook_secret_hmac=secrets.token_bytes(32), stripe_webhook_secret_fingerprint="whfp00000001",
            stripe_portal_configuration_id_ciphertext=None, credential_key_id="k1",
        )
        db_billing.set_billing_group_capabilities(
            id=group["id"], checkout_enabled=None, portal_enabled=None, provisioning_enabled=True, webhooks_enabled=True,
        )
        db_billing.set_billing_group_catalog_sync_status(
            id=group["id"], status="drift", error_redacted=None, synced_at="2026-09-01T10:00:00Z"
        )
        detail = db_billing.get_billing_group_by_hash(billing_group_hash=group["hash"])
        rows, total = db_billing.list_billing_groups(search=group["hash"], limit=10, offset=0)

    assert total == 1 and len(rows) == 1
    for row in (detail, rows[0]):
        info = _group_info(row)
        assert (info.webhooks_enabled, info.provisioning_enabled, info.checkout_enabled) == (True, True, False)
        assert info.has_secret_key is True and info.has_webhook_secret is True
        assert info.catalog_sync_status == "drift"
        assert info.last_catalog_synced_at is not None
        assert not any("ciphertext" in key or key.endswith("_hmac") for key in row), "reads return presence flags only"


@pytest.fixture
def purchase(real_factory, group):
    buyer = real_factory.create_user()
    other_user = real_factory.create_user()
    project = real_factory.create_project()
    other_project = real_factory.create_project()
    purchase_ref = f"bpur-{secrets.token_hex(12)}"
    with _real_db():
        db_billing.record_purchase_event(
            purchase_id=f"bpe-{secrets.token_hex(12)}", history_id=None, user_id=buyer["id"], project_id=project["id"],
            billing_group_id=group["id"], customer_id=None, provider="stripe", purchase_ref=purchase_ref,
            checkout_ref="bco-realdb-checkout", status="paid", credit_product_code="credits_small", quantity=1,
            provider_payment_intent_id_ciphertext=None, provider_payment_intent_id_hmac=None,
            provider_payment_intent_id_fingerprint=None, provider_charge_id_ciphertext=None, provider_charge_id_hmac=None,
            provider_charge_id_fingerprint=None, provider_ref_key_id=None, observed_at=datetime.now(timezone.utc),
            sync_source="webhook", paid_at=datetime.now(timezone.utc), refunded_at=None, disputed_at=None,
            stale_after=None, reason="checkout_payment_completed", safe_metadata={"event_type": "checkout.session.completed"},
        )
    return {
        "ref": purchase_ref,
        "user_hash": buyer["user_hash"],
        "project_hash": project["project_hash"],
        "other_user_hash": other_user["user_hash"],
        "other_project_hash": other_project["project_hash"],
    }


def test_purchase_lookup_returns_the_fact_only_for_its_user_and_project(purchase):
    lookup = lambda **overrides: db_billing.get_purchase_status_by_ref(  # noqa: E731
        **{"user_hash": purchase["user_hash"], "project_hash": purchase["project_hash"], "purchase_ref": purchase["ref"], **overrides}
    )
    with _real_db():
        found = lookup()
        other_user = lookup(user_hash=purchase["other_user_hash"])
        other_project = lookup(project_hash=purchase["other_project_hash"])
        unknown_ref = lookup(purchase_ref="bpur-does-not-exist")

    assert found is not None
    assert (found["purchase_ref"], found["status"], found["credit_product_code"]) == (purchase["ref"], "paid", "credits_small")
    assert found["paid_at"] is not None
    assert not FORBIDDEN_PURCHASE_KEYS & set(found)
    assert not any("ciphertext" in key or "hmac" in key or "fingerprint" in key for key in found)
    assert (other_user, other_project, unknown_ref) == (None, None, None)


@asynccontextmanager
async def _billing_client():
    from src.routes import internal_billing

    app = FastAPI(title="billing real-db purchase status")
    app.include_router(internal_billing.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_s2s_purchase_status_route_reads_the_recorded_purchase(purchase, monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    headers = {"Authorization": f"Bearer {S2S_TOKEN}", "User-Agent": "billing-real-db-test"}
    path = f"/internal/users/{purchase['user_hash']}/billing/purchases/{purchase['ref']}"

    with _real_db():
        async with _billing_client() as client:
            found = await client.get(path, params={"project_hash": purchase["project_hash"]}, headers=headers)
            elsewhere = await client.get(path, params={"project_hash": purchase["other_project_hash"]}, headers=headers)

    assert found.status_code == 200, found.text
    assert found.json()["purchase"]["status"] == "paid"
    assert found.json()["purchase"]["purchase_ref"] == purchase["ref"]
    assert elsewhere.status_code == 404
