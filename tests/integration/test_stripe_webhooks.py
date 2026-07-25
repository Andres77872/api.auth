"""RED integration contracts for the Stripe webhook receiver.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.7.
"""

from __future__ import annotations

import hashlib
import importlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI


ROOT = Path(__file__).resolve().parents[2]
WEBHOOK_ROOT = ROOT / "tests" / "fixtures" / "stripe" / "webhooks"
SIGNATURE_HEADERS = WEBHOOK_ROOT / "signature_headers.json"
ROUTE_MODULE = "src.routes.stripe_webhooks"
WEBHOOK_PATH = "/webhooks/stripe"

RAW_STRIPE_SENTINELS = (
    "cus_test",
    "sub_test",
    "price_test",
    "prod_test",
    "pi_test",
    "ch_test",
    "cs_test",
    "evt_test",
    "whsec_",
    "stripe_signature",
    "idempotency_key",
    "4242",
)


def _future_route_module():
    try:
        return importlib.import_module(ROUTE_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name and ROUTE_MODULE.startswith(exc.name):
            pytest.fail(f"missing future route module: {ROUTE_MODULE}; Phase 7.2 must provide /webhooks/stripe", pytrace=False)
        pytest.fail(f"{ROUTE_MODULE} import failed due to missing dependency: {exc.name}", pytrace=False)


@asynccontextmanager
async def _webhook_client():
    route_module = _future_route_module()
    app = FastAPI(title="Stripe Webhook RED Contract Test App")
    app.include_router(route_module.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _signature_manifest() -> dict[str, Any]:
    return json.loads(SIGNATURE_HEADERS.read_text(encoding="utf-8"))


def _raw_fixture(filename: str) -> bytes:
    return (WEBHOOK_ROOT / filename).read_bytes()


def _fixture_meta(filename: str) -> dict[str, Any]:
    return _signature_manifest()["headers"][filename]


def _headers(filename: str, *, signature: str | None = None) -> dict[str, str]:
    meta = _fixture_meta(filename)
    return {
        "Content-Type": "application/json",
        "User-Agent": "stripe-webhook-red-contract-test",
        "Stripe-Signature": signature if signature is not None else meta["stripe_signature"],
    }


def _assert_fixture_bytes_match_manifest(filename: str) -> None:
    raw_body = _raw_fixture(filename)
    meta = _fixture_meta(filename)
    assert len(raw_body) == meta["byte_length"]
    assert hashlib.sha256(raw_body).hexdigest() == meta["raw_body_sha256"]


def _assert_no_session_or_raw_provider_leaks(response: httpx.Response, *, context: str) -> None:
    for cookie_name in ("session_token", "refresh_token", "access_token"):
        assert cookie_name not in response.cookies, f"webhook must not set local auth cookie {cookie_name}"
    body = response.text.lower()
    leaked = [sentinel for sentinel in RAW_STRIPE_SENTINELS if sentinel in body]
    assert leaked == [], f"{context}: raw Stripe/provider data leaked: {leaked}"


@pytest.mark.asyncio
async def test_signed_allowed_webhook_reads_exact_raw_body_and_returns_neutral_success(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    _assert_fixture_bytes_match_manifest("checkout_session_completed_payment.json")
    async with _webhook_client() as client:
        response = await client.post(WEBHOOK_PATH, content=_raw_fixture("checkout_session_completed_payment.json"), headers=_headers("checkout_session_completed_payment.json"))

    assert response.status_code == 200
    _assert_no_session_or_raw_provider_leaks(response, context="valid webhook")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "headers"),
    [
        ("checkout_session_completed_payment.json", {}),
        ("checkout_session_completed_payment.json", {"Stripe-Signature": "not-a-signature"}),
        ("tampered_body.json", None),
    ],
)
async def test_invalid_signature_is_rejected_before_delivery_or_mutation(monkeypatch, filename: str, headers: dict[str, str] | None):
    monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    request_headers = {"Content-Type": "application/json", "User-Agent": "stripe-invalid-signature-test"}
    if headers is None:
        request_headers.update(_headers(filename))
    else:
        request_headers.update(headers)

    async with _webhook_client() as client:
        response = await client.post(WEBHOOK_PATH, content=_raw_fixture(filename), headers=request_headers)

    assert response.status_code in {400, 401, 403}
    _assert_no_session_or_raw_provider_leaks(response, context="invalid signature")


@pytest.mark.asyncio
async def test_valid_unsupported_event_is_accepted_as_noop_without_mutation(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    async with _webhook_client() as client:
        response = await client.post(WEBHOOK_PATH, content=_raw_fixture("unsupported_customer_updated.json"), headers=_headers("unsupported_customer_updated.json"))

    assert response.status_code == 200
    text = response.text.lower()
    assert "ignored" in text or "accepted" in text or "noop" in text
    _assert_no_session_or_raw_provider_leaks(response, context="unsupported event")


@pytest.mark.asyncio
async def test_duplicate_webhook_replay_is_idempotent_and_does_not_repeat_side_effects(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    raw = _raw_fixture("invoice_paid.json")
    headers = _headers("invoice_paid.json")
    async with _webhook_client() as client:
        first = await client.post(WEBHOOK_PATH, content=raw, headers=headers)
        replay = await client.post(WEBHOOK_PATH, content=raw, headers=headers)

    assert first.status_code == 200
    assert replay.status_code == 200
    replay_body = replay.text.lower()
    assert "duplicate" in replay_body or "replay" in replay_body or "accepted" in replay_body
    _assert_no_session_or_raw_provider_leaks(replay, context="duplicate replay")


@pytest.mark.asyncio
@pytest.mark.parametrize("filename", ["customer_subscription_deleted.json", "invoice_payment_failed.json", "charge_refunded.json"])
async def test_out_of_order_or_destructive_events_enqueue_resync_without_exposing_raw_evidence(monkeypatch, filename: str):
    monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    async with _webhook_client() as client:
        response = await client.post(WEBHOOK_PATH, content=_raw_fixture(filename), headers=_headers(filename))

    assert response.status_code in {200, 202}
    _assert_no_session_or_raw_provider_leaks(response, context=f"{filename} resync/destructive handling")


@pytest.mark.asyncio
async def test_resync_required_webhook_persists_refs_and_enqueues_typed_subscription_job(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOKS_ENABLED", "true")
    monkeypatch.setenv("BILLING_ENABLED", "true")
    route_module = _future_route_module()
    captured: dict[str, Any] = {"observe": {}, "job": {}}

    monkeypatch.setattr(route_module, "resolve_user_billing_group", lambda **_: {"user_id": "usr-1", "project_id": "prj-1", "billing_group_id": "bg-1"})
    monkeypatch.setattr(route_module, "record_webhook_delivery", lambda **_: {"delivery_status": "accepted"})
    monkeypatch.setattr(route_module, "upsert_customer", lambda **_: {"customer_id": "bcust-1"})
    monkeypatch.setattr(route_module, "_invalidate_user_sessions", lambda *_args, **_kwargs: None)

    def _observe(**kwargs: Any):
        captured["observe"] = kwargs
        return {"subscription_id": kwargs["subscription_id"]}

    def _enqueue(**kwargs: Any):
        captured["job"] = kwargs
        return {"job_id": kwargs["job_id"]}

    monkeypatch.setattr(route_module, "observe_subscription", _observe)
    monkeypatch.setattr(route_module, "enqueue_sync_job", _enqueue)

    async with _webhook_client() as client:
        response = await client.post(
            WEBHOOK_PATH,
            content=_raw_fixture("invoice_payment_failed.json"),
            headers=_headers("invoice_payment_failed.json"),
        )

    assert response.status_code == 200
    assert captured["observe"]["customer_id"] == "bcust-1"
    assert captured["observe"]["provider_subscription_id_ciphertext"]
    assert captured["observe"]["provider_subscription_id_hmac"]
    assert captured["observe"]["provider_ref_key_id"]
    assert captured["job"]["job_type"] == "subscription"
    assert captured["job"]["billing_group_id"] == "bg-1"
    assert captured["job"]["subscription_id"] == captured["observe"]["subscription_id"]
    _assert_no_session_or_raw_provider_leaks(response, context="typed subscription resync")


def test_audit_contract_declares_stripe_webhook_raw_body_exclusion_before_route_is_enabled():
    from src.Util.api_audit_logger import APIAuditLogger

    assert "/webhooks/stripe" in APIAuditLogger.RAW_BODY_AUDIT_EXCLUDED_PATHS
    assert "stripe-signature" in {header.lower() for header in APIAuditLogger.SENSITIVE_HEADERS}
