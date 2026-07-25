"""RED integration contracts for dedicated billing S2S routes.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.6.
"""

from __future__ import annotations

import importlib
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.Util.billing.provider import BillingHostedSession
from src.Util.billing.security import encrypt_provider_ref
from src.Util.billing.config import load_billing_config


ROUTE_MODULE = "src.routes.internal_billing"
S2S_TOKEN = "test-billing-s2s-bearer-token-not-real"
USER_HASH = "usrh_fixture_001"
PROJECT_HASH = "prjh_magic_worlds"
READ_PATH = f"/internal/users/{USER_HASH}/billing?project_hash={PROJECT_HASH}"
CHECKOUT_PATH = f"/internal/users/{USER_HASH}/billing/checkout"
PORTAL_PATH = f"/internal/users/{USER_HASH}/billing/portal"
PURCHASE_PATH = f"/internal/users/{USER_HASH}/billing/purchases/bpu_fixture_credit_001?project_hash={PROJECT_HASH}"
RESYNC_PATH = f"/internal/users/{USER_HASH}/billing/resync"

SAFE_TOP_LEVEL_FIELDS = {"success", "message", "user_hash", "project_hash", "provider", "billing", "purchases", "contract_version"}
SAFE_BILLING_FIELDS = {
    "provider",
    "status",
    "plan_code",
    "tier_code",
    "tier_name",
    "link_status",
    "current_period_end",
    "cancel_at_period_end",
    "trial_end",
    "grace_period_until",
    "last_synced_at",
    "stale_after",
    "classification_version",
    "customer_ref",
    "subscription_ref",
}
RAW_STRIPE_SENTINELS = (
    "cus_test",
    "sub_test",
    "price_test",
    "prod_test",
    "pi_test",
    "ch_test",
    "cs_test",
    "evt_test",
    "stripe_signature",
    "webhook_secret",
    "idempotency_key",
    "provider_id_hash",
    "provider_id_fingerprint",
)


def _future_route_module():
    try:
        return importlib.import_module(ROUTE_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name and ROUTE_MODULE.startswith(exc.name):
            pytest.fail(f"missing future route module: {ROUTE_MODULE}; Phase 7.1 must provide billing S2S routes", pytrace=False)
        pytest.fail(f"{ROUTE_MODULE} import failed due to missing dependency: {exc.name}", pytrace=False)


@asynccontextmanager
async def _billing_client():
    route_module = _future_route_module()
    app = FastAPI(title="Billing S2S RED Contract Test App")
    app.include_router(route_module.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _auth_headers(token: str = S2S_TOKEN, *, idem: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}", "User-Agent": "billing-s2s-red-contract-test"}
    if idem:
        headers["Idempotency-Key"] = idem
    return headers


def _json_or_text(response: httpx.Response) -> Any:
    try:
        return response.json()
    except Exception:
        return response.text


def _assert_no_raw_provider_leaks(value: Any, *, context: str) -> None:
    serialized = json.dumps(value, sort_keys=True, default=str).lower() if not isinstance(value, str) else value.lower()
    leaked = [sentinel for sentinel in RAW_STRIPE_SENTINELS if sentinel in serialized]
    assert leaked == [], f"{context}: raw Stripe/provider internals leaked: {leaked}"


def _assert_free_default(payload: dict[str, Any]) -> None:
    assert set(payload) <= SAFE_TOP_LEVEL_FIELDS
    assert payload.get("user_hash") == USER_HASH
    assert payload.get("project_hash") == PROJECT_HASH
    assert payload.get("provider") == "stripe"
    billing = payload.get("billing")
    assert isinstance(billing, dict)
    assert set(billing) <= SAFE_BILLING_FIELDS
    assert billing.get("status") == "free"
    assert billing.get("plan_code") == "free"
    assert billing.get("link_status") == "none"
    assert payload.get("purchases") in ([], None)


def _encrypted_customer_row() -> dict[str, Any]:
    config = load_billing_config()
    encrypted = encrypt_provider_ref(
        raw_ref="cus_test_fixture_project_001",
        key=config.provider_ref_encryption_key,
        key_id=config.provider_ref_encryption_key_id,
        provider="stripe",
    )
    return {
        "provider_customer_id_ciphertext": encrypted.ciphertext,
        "provider_ref_key_id": encrypted.key_id,
        "customer_ref": "bcust-fixture",
    }


def _patch_ready_group(monkeypatch) -> Any:
    route_module = _future_route_module()
    monkeypatch.setattr(
        route_module,
        "resolve_user_billing_group",
        lambda **_: {
            "user_id": "usr-1",
            "project_id": "prj-1",
            "billing_group_id": "bg-1",
            "user_hash": USER_HASH,
            "project_hash": PROJECT_HASH,
        },
    )
    monkeypatch.setattr(route_module, "get_customer_operational_ref", lambda **_: _encrypted_customer_row())
    monkeypatch.setattr(route_module, "_group_stripe_client", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        route_module,
        "_group_stripe_secrets",
        lambda *_args, **_kwargs: SimpleNamespace(secret_key="sk_test_fixture_do_not_use", portal_configuration_id="bpc_test_fixture"),
    )
    monkeypatch.setattr(
        route_module.db_billing,
        "get_billing_group_operational_credentials",
        lambda **_: {
            "id": "bg-1",
            "status": "active",
            "credential_status": "active",
            "checkout_enabled": True,
            "portal_enabled": True,
            "stripe_secret_key_ciphertext": b"encrypted-secret",
            "stripe_portal_configuration_id_ciphertext": b"encrypted-portal",
        },
    )
    monkeypatch.setattr(
        route_module,
        "create_checkout_session",
        lambda **kwargs: BillingHostedSession(
            provider="stripe",
            url="https://checkout.stripe.test/session",
            hosted_ref=kwargs["intent"].checkout_ref,
            checkout_ref=kwargs["intent"].checkout_ref,
            purchase_ref=kwargs["intent"].purchase_ref,
            subscription_ref=kwargs["intent"].subscription_ref,
            safe_metadata={"provider_checkout_session_id": "cs_test_fixture_secret_should_not_serialize"},
        ),
    )
    monkeypatch.setattr(
        route_module,
        "create_portal_session",
        lambda **kwargs: BillingHostedSession(
            provider="stripe",
            url="https://billing.stripe.test/portal",
            hosted_ref=kwargs["portal_ref"],
            portal_ref=kwargs["portal_ref"],
        ),
    )
    monkeypatch.setattr(route_module, "complete_checkout_intent", lambda **_: {"intent_status": "completed"})
    return route_module


@pytest.mark.asyncio
async def test_billing_s2s_read_requires_dedicated_bearer_and_rejects_cookie_or_jwt_authority(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    async with _billing_client() as client:
        no_auth = await client.get(READ_PATH, headers={"User-Agent": "billing-s2s-red-contract-test"})
        cookie_only = await client.get(READ_PATH, cookies={"session_token": "jwt-looking-but-not-s2s"})
        jwt_only = await client.get(READ_PATH, headers={"Authorization": "Bearer header.payload.signature"})
        wrong_bearer = await client.get(READ_PATH, headers=_auth_headers("wrong-billing-token"))

    for response, context in (
        (no_auth, "missing bearer"),
        (cookie_only, "cookie only"),
        (jwt_only, "jwt only"),
        (wrong_bearer, "wrong bearer"),
    ):
        assert response.status_code in {401, 403}
        _assert_no_raw_provider_leaks(_json_or_text(response), context=context)


@pytest.mark.asyncio
async def test_authorized_billing_read_returns_project_scoped_free_default_and_safe_allow_list(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    async with _billing_client() as client:
        response = await client.get(READ_PATH, headers=_auth_headers())

    assert response.status_code == 200
    payload = response.json()
    _assert_free_default(payload)
    _assert_no_raw_provider_leaks(payload, context="free default billing read")
    assert "session_token" not in response.cookies
    assert "refresh_token" not in response.cookies


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [CHECKOUT_PATH, PORTAL_PATH, RESYNC_PATH])
async def test_mutating_billing_s2s_routes_require_dedicated_bearer_and_user_agent(monkeypatch, path: str):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    async with _billing_client() as client:
        response = await client.post(path, json={"project_hash": PROJECT_HASH})
    assert response.status_code in {401, 403, 422}
    _assert_no_raw_provider_leaks(_json_or_text(response), context=f"{path} denial")


@pytest.mark.asyncio
async def test_checkout_and_portal_responses_are_url_plus_opaque_refs_only(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("BILLING_PORTAL_ENABLED", "true")
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("STRIPE_PORTAL_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    _patch_ready_group(monkeypatch)
    checkout_body = {
        "project_hash": PROJECT_HASH,
        "provider": "stripe",
        "intent_type": "subscription",
        "price_ref": {"ref_type": "lookup_key", "value": "magic_worlds_plus_monthly"},
        "plan_code": "magic_worlds_plus",
        "tier_code": "artisan",
        "success_url": "https://app.example.test/billing/success",
        "cancel_url": "https://app.example.test/billing/cancel",
        "client_intent_ref": "intent_subscribe_fixture_001",
    }
    portal_body = {"project_hash": PROJECT_HASH, "provider": "stripe", "return_url": "https://app.example.test/billing"}
    async with _billing_client() as client:
        checkout = await client.post(CHECKOUT_PATH, headers=_auth_headers(idem="idem-subscribe-001"), json=checkout_body)
        portal = await client.post(PORTAL_PATH, headers=_auth_headers(idem="idem-portal-001"), json=portal_body)

    for response, expected_ref in ((checkout, "checkout_ref"), (portal, "portal_ref")):
        assert response.status_code in {200, 201, 202}
        payload = response.json()
        assert set(payload) <= {"success", "message", expected_ref, "purchase_ref", "subscription_ref", "url", "contract_version"}
        assert isinstance(payload.get("url"), str) and payload["url"].startswith("https://")
        assert payload.get(expected_ref, "").startswith(("bco-", "bpo-"))
        _assert_no_raw_provider_leaks(payload, context=f"{expected_ref} response")


@pytest.mark.asyncio
async def test_checkout_and_portal_fail_closed_without_ready_group_or_customer(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("BILLING_PORTAL_ENABLED", "true")
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("STRIPE_PORTAL_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    checkout_body = {
        "project_hash": PROJECT_HASH,
        "provider": "stripe",
        "intent_type": "subscription",
        "price_ref": {"ref_type": "lookup_key", "value": "magic_worlds_plus_monthly"},
        "plan_code": "magic_worlds_plus",
        "tier_code": "artisan",
        "success_url": "https://app.example.test/billing/success",
        "cancel_url": "https://app.example.test/billing/cancel",
        "client_intent_ref": "intent_subscribe_fixture_not_ready",
    }
    portal_body = {"project_hash": PROJECT_HASH, "provider": "stripe", "return_url": "https://app.example.test/billing"}
    async with _billing_client() as client:
        checkout = await client.post(CHECKOUT_PATH, headers=_auth_headers(idem="idem-not-ready"), json=checkout_body)
        portal = await client.post(PORTAL_PATH, headers=_auth_headers(idem="idem-portal-not-ready"), json=portal_body)

    for response, context in ((checkout, "checkout not ready"), (portal, "portal not ready")):
        assert response.status_code in {422, 503}
        assert "billing.example.test" not in response.text
        _assert_no_raw_provider_leaks(_json_or_text(response), context=context)


@pytest.mark.asyncio
async def test_checkout_idempotent_retry_and_conflict_are_neutral(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("STRIPE_BILLING_ENABLED", "true")
    monkeypatch.setenv("STRIPE_CHECKOUT_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    _patch_ready_group(monkeypatch)
    body = {
        "project_hash": PROJECT_HASH,
        "provider": "stripe",
        "intent_type": "credit_purchase",
        "price_ref": {"ref_type": "lookup_key", "value": "credits_small"},
        "credit_product_code": "credits_small",
        "success_url": "https://app.example.test/billing/success",
        "cancel_url": "https://app.example.test/billing/cancel",
        "client_intent_ref": "intent_credit_fixture_001",
    }
    changed = {**body, "credit_product_code": "credits_large"}
    async with _billing_client() as client:
        first = await client.post(CHECKOUT_PATH, headers=_auth_headers(idem="same-key"), json=body)
        replay = await client.post(CHECKOUT_PATH, headers=_auth_headers(idem="same-key"), json=body)
        conflict = await client.post(CHECKOUT_PATH, headers=_auth_headers(idem="same-key"), json=changed)

    assert first.status_code in {200, 201, 202}
    assert replay.status_code in {200, 201, 202}
    assert conflict.status_code in {409, 422}
    _assert_no_raw_provider_leaks(conflict.text, context="idempotency conflict")


@pytest.mark.asyncio
async def test_purchase_status_read_and_resync_are_safe_s2s_only(monkeypatch):
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)
    async with _billing_client() as client:
        purchase = await client.get(PURCHASE_PATH, headers=_auth_headers())
        resync = await client.post(RESYNC_PATH, headers=_auth_headers(), json={"project_hash": PROJECT_HASH, "provider": "stripe", "reason": "contract_test"})
    assert purchase.status_code in {200, 404}
    assert resync.status_code in {200, 202, 404}
    _assert_no_raw_provider_leaks(_json_or_text(purchase), context="purchase status read")
    _assert_no_raw_provider_leaks(_json_or_text(resync), context="resync response")
