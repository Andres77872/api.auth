"""Stripe-specific security helpers over the generic billing core.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.3.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time
from dataclasses import dataclass, field
from typing import Any

from src.Util.billing import idempotency as billing_idempotency
from src.Util.billing import security as billing_security
from src.Util.billing.redaction import RAW_STRIPE_ID_RE, sanitize_billing_sensitive_text


STRIPE_SIGNATURE_RE = re.compile(r"^(?:[A-Za-z0-9_]+=.+)(?:,[A-Za-z0-9_]+=.+)*$")
STRIPE_ID_PREFIXES = ("cus", "sub", "price", "prod", "in", "pi", "ch", "cs", "bps", "evt")


class StripeSecurityError(RuntimeError):
    """Neutral Stripe security failure; never include raw provider material."""


class StripeWebhookSignatureError(StripeSecurityError):
    """Raised when exact raw-body Stripe signature verification fails."""


@dataclass(frozen=True)
class StripeSignatureParts:
    timestamp: int
    signatures: tuple[str, ...] = field(repr=False)


def _ensure_raw_body(raw_body: bytes | bytearray | memoryview | None) -> bytes:
    if isinstance(raw_body, bytes):
        return raw_body
    if isinstance(raw_body, (bytearray, memoryview)):
        return bytes(raw_body)
    raise TypeError("raw_body must be exact bytes")


def _ensure_text(value: Any, *, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise StripeSecurityError(f"{name} is required")
    return text


def parse_stripe_signature_header(signature_header: str | None) -> StripeSignatureParts:
    header = _ensure_text(signature_header, name="Stripe-Signature")
    if not STRIPE_SIGNATURE_RE.match(header):
        raise StripeWebhookSignatureError("Stripe webhook signature invalid")
    values: dict[str, list[str]] = {}
    for part in header.split(","):
        if "=" not in part:
            raise StripeWebhookSignatureError("Stripe webhook signature invalid")
        key, value = part.split("=", 1)
        values.setdefault(key.strip(), []).append(value.strip())
    try:
        timestamp = int(values.get("t", [""])[0])
    except (TypeError, ValueError) as exc:
        raise StripeWebhookSignatureError("Stripe webhook signature invalid") from exc
    signatures = tuple(item for item in values.get("v1", ()) if item)
    if timestamp <= 0 or not signatures:
        raise StripeWebhookSignatureError("Stripe webhook signature invalid")
    return StripeSignatureParts(timestamp=timestamp, signatures=signatures)


def compute_stripe_webhook_signature(
    *,
    raw_body: bytes | bytearray | memoryview,
    timestamp: int,
    webhook_secret: str | bytes,
) -> str:
    payload = _ensure_raw_body(raw_body)
    secret = webhook_secret if isinstance(webhook_secret, bytes) else str(webhook_secret or "").encode("utf-8")
    if not secret:
        raise StripeWebhookSignatureError("Stripe webhook signature invalid")
    signed_payload = str(int(timestamp)).encode("ascii") + b"." + payload
    return hmac.new(secret, signed_payload, hashlib.sha256).hexdigest()


def verify_stripe_signature_header(
    *,
    raw_body: bytes | bytearray | memoryview,
    signature_header: str | None,
    webhook_secret: str | bytes,
    tolerance_seconds: int = 300,
    now: int | float | None = None,
) -> bool:
    """Verify Stripe's v1 signature over exact raw bytes and timestamp.

    ``now`` is injectable for deterministic byte-exact fixture tests. The
    comparison is constant-time and failure messages stay generic.
    """

    payload = _ensure_raw_body(raw_body)
    try:
        parts = parse_stripe_signature_header(signature_header)
        current = int(now if now is not None else time.time())
        tolerance = max(0, int(tolerance_seconds))
        if abs(current - parts.timestamp) > tolerance:
            hmac.compare_digest("0" * 64, "1" * 64)
            return False
        expected = compute_stripe_webhook_signature(
            raw_body=payload,
            timestamp=parts.timestamp,
            webhook_secret=webhook_secret,
        )
        return any(hmac.compare_digest(expected, candidate) for candidate in parts.signatures)
    except Exception:
        hmac.compare_digest("0" * 64, "1" * 64)
        return False


def ensure_valid_stripe_signature(**kwargs: Any) -> None:
    if not verify_stripe_signature_header(**kwargs):
        raise StripeWebhookSignatureError("Stripe webhook signature invalid")


def hmac_stripe_id(
    *,
    raw_id: str | None = None,
    raw_ref: str | None = None,
    kind: str,
    secret: str | bytes,
) -> bytes:
    return billing_security.hmac_provider_ref(
        provider="stripe",
        kind=kind,
        raw_id=raw_id,
        raw_ref=raw_ref,
        secret=secret,
    )


def stripe_id_hmac(**kwargs: Any) -> bytes:
    return hmac_stripe_id(**kwargs)


def fingerprint_stripe_id(
    *,
    raw_id: str | None = None,
    raw_ref: str | None = None,
    kind: str,
    secret: str | bytes,
) -> str:
    return billing_security.fingerprint_from_digest(
        hmac_stripe_id(raw_id=raw_id, raw_ref=raw_ref, kind=kind, secret=secret)
    )


def stripe_id_fingerprint(**kwargs: Any) -> str:
    return fingerprint_stripe_id(**kwargs)


def hmac_stripe_event_id(*, event_id: str, secret: str | bytes) -> bytes:
    return billing_idempotency.webhook_event_id_hmac(provider="stripe", event_id=event_id, secret=secret)


def fingerprint_stripe_event_id(*, event_id: str, secret: str | bytes) -> str:
    return billing_security.fingerprint_from_digest(hmac_stripe_event_id(event_id=event_id, secret=secret))


def detect_raw_stripe_ids(value: Any) -> tuple[str, ...]:
    text = str(value or "")
    return tuple(dict.fromkeys(match.group(0) for match in RAW_STRIPE_ID_RE.finditer(text)))


def contains_raw_stripe_id(value: Any) -> bool:
    return bool(detect_raw_stripe_ids(value))


def sanitize_stripe_log_value(value: Any) -> str:
    return sanitize_billing_sensitive_text(value)


def raw_body_sha256(raw_body: bytes | bytearray | memoryview) -> bytes:
    return billing_security.raw_body_sha256(_ensure_raw_body(raw_body))


def raw_body_sha256_hex(raw_body: bytes | bytearray | memoryview) -> str:
    return raw_body_sha256(raw_body).hex()


__all__ = [
    "STRIPE_ID_PREFIXES",
    "StripeSecurityError",
    "StripeSignatureParts",
    "StripeWebhookSignatureError",
    "compute_stripe_webhook_signature",
    "contains_raw_stripe_id",
    "detect_raw_stripe_ids",
    "ensure_valid_stripe_signature",
    "fingerprint_stripe_event_id",
    "fingerprint_stripe_id",
    "hmac_stripe_event_id",
    "hmac_stripe_id",
    "parse_stripe_signature_header",
    "raw_body_sha256",
    "raw_body_sha256_hex",
    "sanitize_stripe_log_value",
    "stripe_id_fingerprint",
    "stripe_id_hmac",
    "verify_stripe_signature_header",
]
