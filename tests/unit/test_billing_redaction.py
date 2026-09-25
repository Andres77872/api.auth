"""RED unit contracts for billing/Stripe redaction.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 2.3.
"""

from __future__ import annotations

import importlib
import json
from types import ModuleType
from typing import Any

import pytest


REDACTION_MODULE = "src.Util.billing.redaction"
REDACTED_VALUES = {"***FILTERED***", "[REDACTED]", "<redacted>", "REDACTED", None}

RAW_STRIPE_IDS = (
    "cus_test_fixture_project_001",
    "sub_test_fixture_magic_worlds_001",
    "price_test_fixture_magic_worlds_plus_monthly",
    "prod_test_fixture_magic_worlds",
    "in_test_fixture_subscription_cycle_001",
    "pi_test_fixture_credit_001",
    "ch_test_fixture_credit_001",
    "cs_test_fixture_payment_0001",
    "bps_test_fixture_portal_001",
    "evt_test_fixture_checkout_payment_completed",
)

SENSITIVE_PAYLOAD = {
    "stripe_customer_id": RAW_STRIPE_IDS[0],
    "stripe_subscription_id": RAW_STRIPE_IDS[1],
    "stripe_price_id": RAW_STRIPE_IDS[2],
    "stripe_product_id": RAW_STRIPE_IDS[3],
    "stripe_invoice_id": RAW_STRIPE_IDS[4],
    "stripe_payment_intent_id": RAW_STRIPE_IDS[5],
    "stripe_charge_id": RAW_STRIPE_IDS[6],
    "stripe_checkout_session_id": RAW_STRIPE_IDS[7],
    "stripe_portal_session_id": RAW_STRIPE_IDS[8],
    "stripe_event_id": RAW_STRIPE_IDS[9],
    "Stripe-Signature": "t=1893456000,v1=abcdef",
    "stripe_secret_key": "sk_test_fixture_do_not_use",
    "webhook_secret": "whsec_test_stripe_fixture_secret_do_not_use",
    "idempotency_key": "consumer-retry-key-must-not-leak",
    "raw_payload": {"id": RAW_STRIPE_IDS[9], "object": "event"},
    "raw_body": "{raw stripe webhook payload}",
    "card": {"last4": "4242", "brand": "visa", "exp_month": 12, "exp_year": 2030},
    "payment_method_details": {"card": {"last4": "4242"}},
    "receipt_url": "https://pay.stripe.com/receipts/test/secret-receipt",
    "provider_id_hash": "a" * 64,
    "provider_id_fingerprint": "abcdef123456",
    "safe_status": "active",
    "plan_code": "magic_worlds_plus",
}


def _future_redaction_module() -> ModuleType:
    try:
        return importlib.import_module(REDACTION_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name and REDACTION_MODULE.startswith(exc.name):
            pytest.fail(
                f"missing implementation module: {REDACTION_MODULE}; Phase 4.7 must provide recursive billing redaction",
                pytrace=False,
            )
        pytest.fail(f"{REDACTION_MODULE} import failed due to missing dependency: {exc.name}", pytrace=False)


def _call_redact(module: ModuleType, value: Any) -> Any:
    for name in (
        "redact_billing_sensitive_data",
        "redact_billing_payload",
        "filter_billing_sensitive_data",
        "redact_sensitive_data",
    ):
        func = getattr(module, name, None)
        if callable(func):
            return func(value)
    pytest.fail("expected billing redaction callable in future module", pytrace=False)


def _call_sanitize_text(module: ModuleType, value: str) -> str:
    for name in (
        "sanitize_billing_sensitive_text",
        "sanitize_stripe_sensitive_text",
        "redact_billing_sensitive_text",
        "redact_sensitive_text",
    ):
        func = getattr(module, name, None)
        if callable(func):
            return str(func(value))
    pytest.fail("expected billing text sanitizer callable in future module", pytrace=False)


def _flatten(value: Any) -> str:
    return json.dumps(value, sort_keys=True, default=str)


def test_recursive_redaction_removes_raw_stripe_ids_signatures_secrets_and_payment_fields():
    module = _future_redaction_module()
    payload = {
        **SENSITIVE_PAYLOAD,
        "nested": {"items": [dict(SENSITIVE_PAYLOAD)]},
        "safe": {"provider": "stripe", "status": "active", "plan_code": "magic_worlds_plus"},
    }

    redacted = _call_redact(module, payload)
    serialized = _flatten(redacted)

    for raw in RAW_STRIPE_IDS:
        assert raw not in serialized
    for raw in (
        "t=1893456000,v1=abcdef",
        "sk_test_fixture_do_not_use",
        "whsec_test_stripe_fixture_secret_do_not_use",
        "consumer-retry-key-must-not-leak",
        "{raw stripe webhook payload}",
        "4242",
        "visa",
        "https://pay.stripe.com/receipts/test/secret-receipt",
        "abcdef123456",
        "a" * 64,
    ):
        assert raw not in serialized
    assert "magic_worlds_plus" in serialized
    assert "active" in serialized


def test_text_sanitizer_removes_raw_ids_and_secret_like_fragments_from_errors_logs_metrics():
    module = _future_redaction_module()
    raw_message = (
        "customer=cus_test_fixture_project_001 subscription=sub_test_fixture_magic_worlds_001 "
        "price=price_test_fixture_magic_worlds_plus_monthly event=evt_test_fixture_checkout_payment_completed "
        "stripe-signature=t=1893456000,v1=abcdef idempotency_key=consumer-retry-key-must-not-leak "
        "last4=4242 receipt_url=https://pay.stripe.com/receipts/test/secret-receipt"
    )
    sanitized = _call_sanitize_text(module, raw_message)

    for raw in (*RAW_STRIPE_IDS, "t=1893456000,v1=abcdef", "consumer-retry-key-must-not-leak", "4242", "receipt_url="):
        assert raw not in sanitized


def test_dto_forbidden_field_guard_rejects_raw_provider_fields_before_serialization():
    module = _future_redaction_module()
    guard = getattr(module, "assert_billing_dto_is_safe", None) or getattr(module, "assert_no_billing_forbidden_fields", None)
    if not callable(guard):
        pytest.fail("future redaction module must expose DTO forbidden-field guard", pytrace=False)

    with pytest.raises(Exception) as excinfo:
        guard({"provider": "stripe", "status": "active", "stripe_customer_id": "cus_test_fixture_project_001"})
    assert "cus_test_fixture" not in str(excinfo.value)


def test_api_audit_logger_contract_must_add_stripe_signature_and_raw_body_exclusion():
    from src.Util.api_audit_logger import APIAuditLogger

    headers = {header.lower() for header in APIAuditLogger.SENSITIVE_HEADERS}
    raw_body_exclusions = set(APIAuditLogger.RAW_BODY_AUDIT_EXCLUDED_PATHS)

    assert "stripe-signature" in headers, "Stripe-Signature must be classified as sensitive before webhook route ships"
    assert "/webhooks/stripe" in raw_body_exclusions, "/webhooks/stripe raw bodies must be excluded from unsafe audit capture"


# ─── Public identifiers and opaque consumer JSON ─────────────────────────────
# Project and billing group hashes are 64-hex tokens (secrets.token_hex(32).upper()); the
# free-text sanitizer masks any 64-hex run, which used to mask them in every S2S response
# and in the Checkout metadata sent to Stripe.

PROJECT_HASH_64 = "7CCC926F2F5FEB07C973606EB2DF02BC3607C9C5B80A104DF5AAC9A1991F6173"
GROUP_HASH_64 = "A" * 64


def test_public_hash_identifiers_survive_redaction_verbatim():
    from src.Util.billing.redaction import redact_billing_sensitive_data

    redacted = redact_billing_sensitive_data(
        {
            "user_hash": "usr-5b8c7c1e-7f3a-4d2b-9c61-0a1b2c3d4e5f",
            "project_hash": PROJECT_HASH_64,
            "nested": {"billing_group_hash": GROUP_HASH_64},
        }
    )

    assert redacted["user_hash"] == "usr-5b8c7c1e-7f3a-4d2b-9c61-0a1b2c3d4e5f"
    assert redacted["project_hash"] == PROJECT_HASH_64
    assert redacted["nested"]["billing_group_hash"] == GROUP_HASH_64


def test_64_hex_values_stay_masked_outside_public_identifier_fields():
    from src.Util.billing.redaction import REDACTED, redact_billing_sensitive_data, sanitize_billing_sensitive_text

    redacted = redact_billing_sensitive_data({"reason": PROJECT_HASH_64, "note": f"digest {PROJECT_HASH_64}"})

    assert redacted["reason"] == REDACTED
    assert PROJECT_HASH_64 not in redacted["note"]
    assert PROJECT_HASH_64 not in sanitize_billing_sensitive_text(f"project_hash={PROJECT_HASH_64}")


def test_public_identifier_fields_do_not_launder_provider_ids_or_secrets():
    from src.Util.billing.redaction import redact_billing_sensitive_data

    redacted = redact_billing_sensitive_data(
        {"user_hash": "cus_test_fixture_project_001", "project_hash": "sk_test_fixture_do_not_use"}
    )

    assert "cus_test_fixture_project_001" not in json.dumps(redacted)
    assert "sk_test_fixture_do_not_use" not in json.dumps(redacted)


def test_catalog_features_keep_consumer_key_names_and_pass_the_dto_guard():
    """`features` keys like `card` or `*secret*` used to turn the S2S catalog read into a 500."""

    from src.Util.billing.redaction import assert_billing_dto_is_safe, redact_billing_sensitive_data

    payload = {
        "success": True,
        "billing_group_hash": GROUP_HASH_64,
        "subscriptions": [
            {
                "plan_code": "plus",
                "features": {"card": "gold", "secret_level": 3, "fingerprint_scanner": True, "tiers": [{"brand": "x"}]},
            }
        ],
    }

    redacted = redact_billing_sensitive_data(payload)
    assert_billing_dto_is_safe(redacted)

    assert redacted["subscriptions"][0]["features"] == payload["subscriptions"][0]["features"]
    assert redacted["billing_group_hash"] == GROUP_HASH_64


def test_catalog_feature_values_are_still_scrubbed_of_provider_ids():
    from src.Util.billing.redaction import BillingRedactionError, assert_billing_dto_is_safe, redact_billing_sensitive_data

    payload = {"subscriptions": [{"features": {"card": "price_test_fixture_magic_worlds_plus_monthly"}}]}

    redacted = redact_billing_sensitive_data(payload)
    assert "price_test_fixture" not in json.dumps(redacted)
    assert set(redacted["subscriptions"][0]["features"]) == {"card"}
    with pytest.raises(BillingRedactionError):
        assert_billing_dto_is_safe(payload)
