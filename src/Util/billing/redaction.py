"""Recursive billing/Stripe redaction primitives.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 4.7.
"""

from __future__ import annotations

import re
from dataclasses import asdict, is_dataclass
from typing import Any, Mapping


REDACTED = "***FILTERED***"

RAW_STRIPE_ID_RE = re.compile(r"\b(?:cus|sub|price|prod|in|pi|ch|cs|bps|evt)_[A-Za-z0-9_./-]+", re.IGNORECASE)
# Stripe secret material: secret keys (sk_), restricted keys (rk_), and webhook signing
# secrets (whsec_). Per-billing-group credentials must never reach logs/audit.
RAW_STRIPE_SECRET_RE = re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]+|\bwhsec_[A-Za-z0-9]+", re.IGNORECASE)
STRIPE_SIGNATURE_VALUE_RE = re.compile(r"\bt=\d{5,},v1=[A-Za-z0-9,_=-]+", re.IGNORECASE)
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(?:stripe[-_ ]?signature|authorization|api[-_]?key|token|secret|idempotency[-_]?key|client[-_]?secret)\b\s*[:=]\s*[^\s;&]+",
    re.IGNORECASE,
)
RECEIPT_URL_ASSIGNMENT_RE = re.compile(r"\breceipt_url\s*[:=]\s*https?://\S+", re.IGNORECASE)
LAST4_ASSIGNMENT_RE = re.compile(r"\blast4\s*[:=]\s*\d{4}\b", re.IGNORECASE)
CARD_FIELD_ASSIGNMENT_RE = re.compile(r"\b(?:brand|exp_month|exp_year)\s*[:=]\s*[^\s,;&]+", re.IGNORECASE)
STRICT_HASH_VALUE_RE = re.compile(r"\b[a-f0-9]{64}\b", re.IGNORECASE)

BILLING_FORBIDDEN_RESPONSE_FIELD_NAMES = frozenset(
    {
        "access_token",
        "refresh_token",
        "session_token",
        "api_key",
        "stripe_customer_id",
        "stripe_subscription_id",
        "stripe_price_id",
        "stripe_product_id",
        "stripe_invoice_id",
        "stripe_payment_intent_id",
        "stripe_charge_id",
        "stripe_checkout_session_id",
        "stripe_portal_session_id",
        "stripe_event_id",
        "provider_id",
        "provider_id_hash",
        "provider_id_hmac",
        "provider_id_fingerprint",
        "provider_event_id_hmac",
        "provider_event_id_fingerprint",
        "provider_ref_key",
        "provider_ref_key_id",
        "provider_payload",
        "raw_payload",
        "raw_body",
        "stripe_signature",
        "stripe-signature",
        "webhook_secret",
        "stripe_secret_key",
        "billing_s2s_bearer_token",
        "s2s_bearer_token",
        "idempotency_key",
        "card",
        "payment_method",
        "payment_method_details",
        "last4",
        "brand",
        "exp_month",
        "exp_year",
        "receipt_url",
        "client_secret",
        "hmac_secret",
        "id_hmac_secret",
    }
)
NORMALIZED_BILLING_FORBIDDEN_RESPONSE_FIELD_NAMES = frozenset(
    field.replace("-", "_") for field in BILLING_FORBIDDEN_RESPONSE_FIELD_NAMES
)
SENSITIVE_FIELD_FRAGMENTS = frozenset(
    {
        "secret",
        "signature",
        "idempotency",
        "raw_payload",
        "raw_body",
        "provider_payload",
        "provider_response",
        "provider_id_hash",
        "provider_id_hmac",
        "provider_id_fingerprint",
        "fingerprint",
        "hmac",
        "payment_method",
        "receipt_url",
        "client_secret",
    }
)
HOSTED_BILLING_URL_FIELDS = frozenset({"url", "checkout_url", "portal_url", "hosted_url"})
HOSTED_BILLING_URL_PREFIXES = ("https://checkout.stripe.com/", "https://billing.stripe.com/")


class BillingRedactionError(RuntimeError):
    """Raised when a payload attempts to expose billing/provider internals."""


def _normalize_field_name(name: Any) -> str:
    return str(name or "").strip().lower().replace("-", "_")


def is_billing_sensitive_field(name: Any) -> bool:
    normalized = _normalize_field_name(name)
    if normalized in NORMALIZED_BILLING_FORBIDDEN_RESPONSE_FIELD_NAMES:
        return True
    return any(fragment in normalized for fragment in SENSITIVE_FIELD_FRAGMENTS)


def _is_hosted_billing_url(key: Any, value: Any) -> bool:
    normalized = _normalize_field_name(key)
    text = str(value or "")
    return normalized in HOSTED_BILLING_URL_FIELDS and text.startswith(HOSTED_BILLING_URL_PREFIXES)


def sanitize_billing_sensitive_text(value: Any) -> str:
    text = str(value or "")
    if not text:
        return text
    sanitized = RECEIPT_URL_ASSIGNMENT_RE.sub(REDACTED, text)
    sanitized = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(0).split('=')[0].split(':')[0]}={REDACTED}", sanitized)
    sanitized = STRIPE_SIGNATURE_VALUE_RE.sub(REDACTED, sanitized)
    sanitized = RAW_STRIPE_SECRET_RE.sub(REDACTED, sanitized)
    sanitized = RAW_STRIPE_ID_RE.sub(REDACTED, sanitized)
    sanitized = LAST4_ASSIGNMENT_RE.sub(f"last4={REDACTED}", sanitized)
    sanitized = CARD_FIELD_ASSIGNMENT_RE.sub(lambda match: f"{match.group(0).split('=')[0].split(':')[0]}={REDACTED}", sanitized)
    sanitized = STRICT_HASH_VALUE_RE.sub(REDACTED, sanitized)
    return sanitized


def sanitize_stripe_sensitive_text(value: Any) -> str:
    return sanitize_billing_sensitive_text(value)


def redact_billing_sensitive_text(value: Any) -> str:
    return sanitize_billing_sensitive_text(value)


def redact_sensitive_text(value: Any) -> str:
    return sanitize_billing_sensitive_text(value)


def redact_billing_sensitive_data(value: Any, *, _key: Any = None) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if is_billing_sensitive_field(key):
                redacted[key] = REDACTED
            elif _is_hosted_billing_url(key, item):
                redacted[key] = item
            else:
                redacted[key] = redact_billing_sensitive_data(item, _key=key)
        return redacted
    if isinstance(value, list):
        return [redact_billing_sensitive_data(item, _key=_key) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_billing_sensitive_data(item, _key=_key) for item in value)
    if isinstance(value, set):
        return {redact_billing_sensitive_data(item, _key=_key) for item in value}
    if isinstance(value, str):
        if _is_hosted_billing_url(_key, value):
            return value
        return sanitize_billing_sensitive_text(value)
    return value


def redact_billing_payload(value: Any) -> Any:
    return redact_billing_sensitive_data(value)


def filter_billing_sensitive_data(value: Any) -> Any:
    return redact_billing_sensitive_data(value)


def redact_sensitive_data(value: Any) -> Any:
    return redact_billing_sensitive_data(value)


def _iter_mapping_items(value: Any):
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield key, item


def _contains_raw_provider_text(value: Any) -> bool:
    if isinstance(value, str):
        return bool(
            RAW_STRIPE_ID_RE.search(value)
            or RAW_STRIPE_SECRET_RE.search(value)
            or STRIPE_SIGNATURE_VALUE_RE.search(value)
        )
    if isinstance(value, Mapping):
        return any(_contains_raw_provider_text(item) or is_billing_sensitive_field(key) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_raw_provider_text(item) for item in value)
    return False


def assert_billing_dto_is_safe(value: Any) -> None:
    for key, item in _iter_mapping_items(value) or ():
        if is_billing_sensitive_field(key):
            raise BillingRedactionError("billing DTO contains forbidden provider field")
        if _contains_raw_provider_text(item):
            raise BillingRedactionError("billing DTO contains forbidden provider data")
        if isinstance(item, Mapping):
            assert_billing_dto_is_safe(item)
        elif isinstance(item, (list, tuple, set)):
            for child in item:
                if isinstance(child, Mapping):
                    assert_billing_dto_is_safe(child)
                elif _contains_raw_provider_text(child):
                    raise BillingRedactionError("billing DTO contains forbidden provider data")


def assert_no_billing_forbidden_fields(value: Any) -> None:
    assert_billing_dto_is_safe(value)


def scrub_billing_log_payload(value: Any) -> Any:
    return redact_billing_sensitive_data(value)


def scrub_billing_error(value: Any) -> Any:
    return redact_billing_sensitive_data(value)


def scrub_billing_metric_label(value: Any) -> str:
    return sanitize_billing_sensitive_text(value)


__all__ = [
    "BILLING_FORBIDDEN_RESPONSE_FIELD_NAMES",
    "BillingRedactionError",
    "NORMALIZED_BILLING_FORBIDDEN_RESPONSE_FIELD_NAMES",
    "RAW_STRIPE_ID_RE",
    "RAW_STRIPE_SECRET_RE",
    "REDACTED",
    "assert_billing_dto_is_safe",
    "assert_no_billing_forbidden_fields",
    "filter_billing_sensitive_data",
    "is_billing_sensitive_field",
    "redact_billing_payload",
    "redact_billing_sensitive_data",
    "redact_billing_sensitive_text",
    "redact_sensitive_data",
    "redact_sensitive_text",
    "sanitize_billing_sensitive_text",
    "sanitize_stripe_sensitive_text",
    "scrub_billing_error",
    "scrub_billing_log_payload",
    "scrub_billing_metric_label",
]
