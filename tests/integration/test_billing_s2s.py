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
RETURN_ORIGIN = "https://app.example.test"

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
    monkeypatch.setenv("BILLING_RETURN_URL_ALLOWLIST", RETURN_ORIGIN)
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
    monkeypatch.setenv("BILLING_RETURN_URL_ALLOWLIST", RETURN_ORIGIN)
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
    monkeypatch.setenv("BILLING_RETURN_URL_ALLOWLIST", RETURN_ORIGIN)
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


# Checkout issues purchase refs as `bpur-...`; the response model only accepts opaque `b*-` refs.
PURCHASE_REF = "bpur-fixture-credit-001"
STORED_PURCHASE_PATH = f"/internal/users/{USER_HASH}/billing/purchases/{PURCHASE_REF}?project_hash={PROJECT_HASH}"


def _enable_s2s(monkeypatch) -> None:
    monkeypatch.setenv("BILLING_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_ENABLED", "true")
    monkeypatch.setenv("BILLING_S2S_BEARER_TOKEN", S2S_TOKEN)


@pytest.mark.asyncio
async def test_purchase_status_read_is_wired_to_the_purchase_lookup_procedure(monkeypatch):
    """The route used to hold ``get_purchase_status_by_ref = None`` and answered 404 for every ref."""

    _enable_s2s(monkeypatch)
    route_module = _future_route_module()
    calls: list[tuple[str, list[Any]]] = []

    def _callproc_one(proc_name, args, *, context, commit=False):
        calls.append((proc_name, list(args)))
        return {
            "purchase_ref": PURCHASE_REF,
            "provider": "stripe",
            "status": "paid",
            "credit_product_code": "credits_small",
            "quantity": 1,
            "paid_at": "2026-01-02T03:04:05Z",
            "refunded_at": None,
            "disputed_at": None,
            "last_synced_at": "2026-01-02T03:04:06Z",
            "stale_after": None,
        }

    monkeypatch.setattr(route_module.db_billing, "_callproc_one", _callproc_one)
    async with _billing_client() as client:
        response = await client.get(STORED_PURCHASE_PATH, headers=_auth_headers())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["user_hash"] == USER_HASH and payload["project_hash"] == PROJECT_HASH
    purchase = payload["purchase"]
    assert purchase["purchase_ref"] == PURCHASE_REF
    assert purchase["status"] == "paid"
    assert purchase["credit_product_code"] == "credits_small"
    assert purchase["paid_at"].startswith("2026-01-02T03:04:05")
    assert calls == [
        ("sp_billing_get_purchase_status_by_ref", [USER_HASH, PROJECT_HASH, PURCHASE_REF, "stripe"])
    ]
    _assert_no_raw_provider_leaks(payload, context="purchase status read")


@pytest.mark.asyncio
async def test_purchase_status_read_is_404_when_the_purchase_is_not_in_this_user_and_project(monkeypatch):
    _enable_s2s(monkeypatch)
    route_module = _future_route_module()
    monkeypatch.setattr(route_module.db_billing, "_callproc_one", lambda *_args, **_kwargs: None)
    async with _billing_client() as client:
        response = await client.get(STORED_PURCHASE_PATH, headers=_auth_headers())

    assert response.status_code == 404
    assert response.json() == {"success": False, "message": "Resource not found."}


# ─── Real identifier formats ─────────────────────────────────────────────────
# `user_hash` is `usr-<uuid4>`; project and billing group hashes are 64 uppercase hex
# characters. The fixture hashes above are neither, which hid both S2S read defects.

REAL_USER_HASH = "usr-5b8c7c1e-7f3a-4d2b-9c61-0a1b2c3d4e5f"
REAL_PROJECT_HASH = "7CCC926F2F5FEB07C973606EB2DF02BC3607C9C5B80A104DF5AAC9A1991F6173"
REAL_GROUP_HASH = "0F1E2D3C4B5A69788796A5B4C3D2E1F00F1E2D3C4B5A69788796A5B4C3D2E1F0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "customer_ref",
    ["bcust-de7711233f9b877f28ac38c9b1495e1a", "bcustref-0123456789abcdef01234567"],
    ids=["issued-by-checkout", "issued-by-older-webhook"],
)
async def test_paying_user_status_read_returns_the_stored_subscription(monkeypatch, customer_ref: str):
    """A stored customer ref used to fail the response model; the route then answered `free`."""

    _enable_s2s(monkeypatch)
    route_module = _future_route_module()
    monkeypatch.setattr(
        route_module,
        "get_current_by_user_project",
        lambda **_: {
            "user_hash": REAL_USER_HASH,
            "project_hash": REAL_PROJECT_HASH,
            "billing_group_hash": REAL_GROUP_HASH,
            "provider": "stripe",
            "status": "active",
            "plan_code": "magic_worlds_plus",
            "tier_code": "artisan",
            "link_status": "linked",
            "cancel_at_period_end": False,
            "current_period_end": "2030-02-01T00:00:00",
            "classification_version": 2,
            "customer_ref": customer_ref,
            "subscription_ref": "bsub-b2dbca0a1198e8051126c02b578465c4",
        },
    )
    async with _billing_client() as client:
        response = await client.get(
            f"/internal/users/{REAL_USER_HASH}/billing?project_hash={REAL_PROJECT_HASH}", headers=_auth_headers()
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["user_hash"] == REAL_USER_HASH
    assert payload["project_hash"] == REAL_PROJECT_HASH, "the 64-hex project hash must not come back as ***FILTERED***"
    billing = payload["billing"]
    assert billing["status"] == "active"
    assert billing["plan_code"] == "magic_worlds_plus"
    assert billing["customer_ref"] == customer_ref
    assert billing["subscription_ref"] == "bsub-b2dbca0a1198e8051126c02b578465c4"
    assert "***FILTERED***" not in response.text
    _assert_no_raw_provider_leaks(payload, context="paying user status read")


@pytest.mark.asyncio
async def test_catalog_read_returns_features_with_provider_like_key_names_and_the_group_hash(monkeypatch):
    """A `features` key such as `card` or one containing `secret`/`fingerprint` used to make this read 500."""

    _enable_s2s(monkeypatch)
    route_module = _future_route_module()
    features = {"card": "gold", "secret_level": 3, "fingerprint_scanner": True, "credits": 0}
    monkeypatch.setattr(
        route_module,
        "list_catalog_for_project",
        lambda **_: [
            {
                "project_hash": REAL_PROJECT_HASH,
                "billing_group_hash": REAL_GROUP_HASH,
                "provider": "stripe",
                "item_type": "subscription_plan",
                "plan_code": "plus",
                "display_name": "Plus",
                "currency": "usd",
                "unit_amount": 999,
                "recurring_interval": "month",
                "lookup_key": "plus_monthly",
                "features": features,
                "active": 1,
            }
        ],
    )
    async with _billing_client() as client:
        response = await client.get(f"/internal/projects/{REAL_PROJECT_HASH}/billing/catalog", headers=_auth_headers())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["project_hash"] == REAL_PROJECT_HASH
    assert payload["billing_group_hash"] == REAL_GROUP_HASH
    assert payload["subscriptions"][0]["features"] == features


def _checkout_body(project_hash: str = PROJECT_HASH) -> dict[str, Any]:
    return {
        "project_hash": project_hash,
        "provider": "stripe",
        "intent_type": "subscription",
        "price_ref": {"ref_type": "lookup_key", "value": "magic_worlds_plus_monthly"},
        "plan_code": "magic_worlds_plus",
        "tier_code": "artisan",
        "success_url": "https://app.example.test/billing/success",
        "cancel_url": "https://app.example.test/billing/cancel",
    }


def _enable_hosted_flows(monkeypatch) -> Any:
    for name in (
        "BILLING_CHECKOUT_ENABLED",
        "BILLING_PORTAL_ENABLED",
        "STRIPE_BILLING_ENABLED",
        "STRIPE_CHECKOUT_ENABLED",
        "STRIPE_PORTAL_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    _enable_s2s(monkeypatch)
    route_module = _patch_ready_group(monkeypatch)
    sessions: list[str] = []
    monkeypatch.setattr(route_module, "create_checkout_session", lambda **_: sessions.append("checkout"))
    monkeypatch.setattr(route_module, "create_portal_session", lambda **_: sessions.append("portal"))
    return sessions


@pytest.mark.asyncio
async def test_checkout_and_portal_refuse_every_return_url_while_the_allowlist_is_empty(monkeypatch):
    sessions = _enable_hosted_flows(monkeypatch)
    monkeypatch.delenv("BILLING_RETURN_URL_ALLOWLIST", raising=False)
    monkeypatch.delenv("BILLING_ALLOWED_RETURN_ORIGINS", raising=False)
    portal_body = {"project_hash": PROJECT_HASH, "provider": "stripe", "return_url": "https://evil.example.test/steal"}
    async with _billing_client() as client:
        checkout = await client.post(CHECKOUT_PATH, headers=_auth_headers(idem="idem-empty-allowlist"), json=_checkout_body())
        portal = await client.post(PORTAL_PATH, headers=_auth_headers(idem="idem-portal-empty-allowlist"), json=portal_body)

    assert checkout.status_code == 503, checkout.text
    assert portal.status_code == 503, portal.text
    assert sessions == [], "no Stripe session may be created without an allowlist"


@pytest.mark.asyncio
async def test_checkout_and_portal_reject_a_return_url_outside_the_allowlist(monkeypatch):
    sessions = _enable_hosted_flows(monkeypatch)
    monkeypatch.setenv("BILLING_RETURN_URL_ALLOWLIST", "https://other.example.test")
    portal_body = {"project_hash": PROJECT_HASH, "provider": "stripe", "return_url": "https://app.example.test/billing"}
    async with _billing_client() as client:
        checkout = await client.post(CHECKOUT_PATH, headers=_auth_headers(idem="idem-outside-allowlist"), json=_checkout_body())
        portal = await client.post(PORTAL_PATH, headers=_auth_headers(idem="idem-portal-outside-allowlist"), json=portal_body)

    assert checkout.status_code == 422, checkout.text
    assert portal.status_code == 422, portal.text
    assert sessions == []


@pytest.mark.asyncio
async def test_resync_request_queues_a_user_level_job_the_worker_can_resolve(monkeypatch):
    """The job carries the user and billing group; the worker resolves the Stripe refs from them."""

    _enable_s2s(monkeypatch)
    monkeypatch.setenv("BILLING_SYNC_ENABLED", "true")
    route_module = _future_route_module()
    monkeypatch.setattr(
        route_module,
        "resolve_user_billing_group",
        lambda **_: {"user_id": "usr-1", "project_id": "prj-1", "billing_group_id": "bg-1"},
    )
    jobs: list[dict[str, Any]] = []
    monkeypatch.setattr(route_module, "enqueue_sync_job", lambda **kwargs: jobs.append(kwargs) or {"job_id": kwargs["job_id"]})
    async with _billing_client() as client:
        response = await client.post(
            f"/internal/users/{REAL_USER_HASH}/billing/resync",
            headers=_auth_headers(),
            json={"project_hash": REAL_PROJECT_HASH, "reason": "support_ticket"},
        )

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "queued"
    assert response.json()["project_hash"] == REAL_PROJECT_HASH
    [job] = jobs
    assert job["job_type"] == "webhook_resync"
    assert job["user_id"] == "usr-1" and job["billing_group_id"] == "bg-1"
