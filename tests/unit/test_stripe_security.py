"""RED unit contracts for Stripe signature/config/Portal security.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.4.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
WEBHOOK_ROOT = ROOT / "tests" / "fixtures" / "stripe" / "webhooks"
SIGNATURE_HEADERS = WEBHOOK_ROOT / "signature_headers.json"
WEBHOOK_MODULE = "src.Util.stripe.webhooks"
CONFIG_MODULE = "src.Util.stripe.config"
PORTAL_MODULE = "src.Util.stripe.portal"
SUPPORTED_API_VERSION = "2026-05-27.dahlia"
SUPPORTED_SDK_VERSION = "15.2.1"


def _future_module(module_name: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and module_name.startswith(exc.name):
            pytest.fail(f"missing implementation module: {module_name}; Phase 6 must provide Stripe security/config helpers", pytrace=False)
        pytest.fail(f"{module_name} import failed due to missing dependency: {exc.name}", pytrace=False)


def _signature_manifest() -> dict[str, Any]:
    return json.loads(SIGNATURE_HEADERS.read_text(encoding="utf-8"))


def _raw_fixture(filename: str) -> bytes:
    return (WEBHOOK_ROOT / filename).read_bytes()


def _fixture_meta(filename: str) -> dict[str, Any]:
    return _signature_manifest()["headers"][filename]


def _expected_signature(raw_body: bytes, timestamp: int, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), f"{timestamp}.".encode("utf-8") + raw_body, hashlib.sha256).hexdigest()


def _verify(module: ModuleType, raw_body: bytes, signature_header: str | None, *, now: int | None = None) -> Any:
    last_error: TypeError | None = None
    for name in (
        "verify_stripe_webhook_signature",
        "construct_verified_stripe_event",
        "verify_webhook_event",
        "construct_event",
    ):
        func = getattr(module, name, None)
        if not callable(func):
            continue
        attempts = (
            {
                "raw_body": raw_body,
                "signature_header": signature_header,
                "webhook_secret": _signature_manifest()["fixture_secret"],
                "tolerance_seconds": _signature_manifest()["tolerance_seconds"],
                "now": now,
            },
            {
                "payload": raw_body,
                "sig_header": signature_header,
                "secret": _signature_manifest()["fixture_secret"],
                "tolerance": _signature_manifest()["tolerance_seconds"],
                "current_timestamp": now,
            },
            {
                "raw_body": raw_body,
                "stripe_signature": signature_header,
                "secret": _signature_manifest()["fixture_secret"],
            },
        )
        for kwargs in attempts:
            clean_kwargs = {key: value for key, value in kwargs.items() if value is not None}
            try:
                return func(**clean_kwargs)
            except TypeError as exc:
                last_error = exc
                continue
    detail = f"; last TypeError: {last_error}" if last_error else ""
    pytest.fail(f"expected Stripe webhook verification callable{detail}", pytrace=False)


def _assert_rejected(module: ModuleType, raw_body: bytes, signature_header: str | None, *, now: int | None = None) -> None:
    try:
        result = _verify(module, raw_body, signature_header, now=now)
    except Exception as exc:
        message = str(exc).lower()
        assert "whsec_" not in message
        assert "cus_test" not in message
        return
    assert result is False or getattr(result, "valid", None) is False or (isinstance(result, dict) and result.get("valid") is False)


def test_fixture_signature_headers_match_hmac_sha256_over_exact_raw_bytes():
    manifest = _signature_manifest()
    secret = manifest["fixture_secret"]
    timestamp = manifest["timestamp"]
    filename = "checkout_session_completed_subscription.json"
    raw_body = _raw_fixture(filename)
    meta = _fixture_meta(filename)

    assert len(raw_body) == meta["byte_length"]
    assert hashlib.sha256(raw_body).hexdigest() == meta["raw_body_sha256"]
    assert raw_body.endswith(b"\n"), "Stripe fixtures must preserve final LF in signed bytes"
    expected = _expected_signature(raw_body, timestamp, secret)
    assert meta["stripe_signature"] == f"t={timestamp},v1={expected}"


def test_valid_stripe_signature_accepts_exact_raw_body_and_returns_event_type():
    module = _future_module(WEBHOOK_MODULE)
    filename = "checkout_session_completed_subscription.json"
    raw_body = _raw_fixture(filename)
    result = _verify(module, raw_body, _fixture_meta(filename)["stripe_signature"], now=_signature_manifest()["timestamp"])

    if isinstance(result, bool):
        assert result is True
        return
    event_type = result.get("type") if isinstance(result, dict) else getattr(result, "type", None)
    assert event_type == "checkout.session.completed"


def test_tampered_missing_malformed_and_expired_signatures_are_rejected_before_json_trust():
    module = _future_module(WEBHOOK_MODULE)
    filename = "checkout_session_completed_subscription.json"
    raw_body = _raw_fixture(filename)
    valid_header = _fixture_meta(filename)["stripe_signature"]
    expired_now = _signature_manifest()["timestamp"] + _signature_manifest()["tolerance_seconds"] + 1

    _assert_rejected(module, raw_body + b" ", valid_header, now=_signature_manifest()["timestamp"])
    _assert_rejected(module, raw_body, None, now=_signature_manifest()["timestamp"])
    _assert_rejected(module, raw_body, "not-a-stripe-signature", now=_signature_manifest()["timestamp"])
    _assert_rejected(module, raw_body, valid_header, now=expired_now)
    _assert_rejected(module, _raw_fixture("tampered_body.json"), _fixture_meta("tampered_body.json")["stripe_signature"], now=_signature_manifest()["timestamp"])


def test_stripe_sdk_and_api_version_pins_are_contractual_and_mismatch_fails_closed():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert "stripe==15.2.1" in requirements

    config = _future_module(CONFIG_MODULE)
    assert getattr(config, "SUPPORTED_STRIPE_SDK_VERSION", SUPPORTED_SDK_VERSION) == SUPPORTED_SDK_VERSION
    assert getattr(config, "SUPPORTED_STRIPE_API_VERSION", SUPPORTED_API_VERSION) == SUPPORTED_API_VERSION

    readiness = getattr(config, "validate_stripe_runtime_readiness", None) or getattr(config, "stripe_runtime_readiness", None)
    if not callable(readiness):
        pytest.fail("future Stripe config must expose fail-closed SDK/API readiness validation", pytrace=False)
    result = readiness(installed_sdk_version="15.2.0", configured_api_version=SUPPORTED_API_VERSION, stripe_enabled=True)
    serialized = json.dumps(result, default=str).lower() if not isinstance(result, str) else result.lower()
    assert "not_ready" in serialized or "mismatch" in serialized or "false" in serialized


def test_restricted_portal_configuration_rejects_plan_updates():
    portal = _future_module(PORTAL_MODULE)
    validate = getattr(portal, "validate_restricted_portal_configuration", None) or getattr(portal, "assert_portal_plan_changes_disabled", None)
    if not callable(validate):
        pytest.fail("future Stripe Portal module must validate restricted MVP Portal configuration", pytrace=False)

    forbidden_config = {
        "features": {
            "customer_update": {"enabled": True, "allowed_updates": ["email", "address"]},
            "payment_method_update": {"enabled": True},
            "subscription_cancel": {"enabled": True},
            "subscription_update": {"enabled": True, "products": [{"prices": ["price_test_fixture"]}]},
        }
    }
    with pytest.raises(Exception):
        validate(forbidden_config)
