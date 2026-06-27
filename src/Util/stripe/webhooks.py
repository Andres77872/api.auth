"""Stripe webhook verification and event envelope extraction.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.8.

Verification operates on exact raw request bytes before JSON trust. SDK-backed
construction is supported for runtime use; deterministic tests can inject
``now`` and use the local HMAC verifier with the same Stripe signing scheme.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from src.Util import auth_constants as constants
from src.Util.billing.idempotency import webhook_event_id_hmac
from src.Util.billing.provider import VerifiedProviderEvent
from src.Util.billing.security import fingerprint_from_digest, raw_body_sha256
from src.Util.error_handler import ErrorCode, StripeFlowError
from src.Util.stripe.config import (
    DEFAULT_STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS,
    SUPPORTED_STRIPE_API_VERSION,
    load_stripe_config,
    validate_stripe_runtime_readiness,
)
from src.Util.stripe.security import StripeWebhookSignatureError, verify_stripe_signature_header


class StripeWebhookVerificationError(StripeFlowError):
    """Neutral fail-closed Stripe webhook verification error."""

    def __init__(self, message: str | None = None, *, status_code: int | None = None) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.STRIPE_WEBHOOK_SIGNATURE_INVALID,
            status_code=status_code or 401,
        )


def _stripe_module():
    import stripe  # type: ignore[import-not-found]

    return stripe


def _ensure_raw_body(raw_body: bytes | bytearray | memoryview | None) -> bytes:
    if isinstance(raw_body, bytes):
        return raw_body
    if isinstance(raw_body, (bytearray, memoryview)):
        return bytes(raw_body)
    raise StripeWebhookVerificationError("Request could not be completed.")


def _event_mapping(event: Any) -> dict[str, Any]:
    if isinstance(event, Mapping):
        return {str(key): value for key, value in event.items()}
    if hasattr(event, "to_dict_recursive") and callable(event.to_dict_recursive):
        value = event.to_dict_recursive()
        if isinstance(value, Mapping):
            return {str(key): item for key, item in value.items()}
    if hasattr(event, "to_dict") and callable(event.to_dict):
        value = event.to_dict()
        if isinstance(value, Mapping):
            return {str(key): item for key, item in value.items()}
    try:
        return dict(event)
    except Exception:
        raise StripeWebhookVerificationError("Request could not be completed.")


def _parse_json_event(raw_body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise StripeWebhookVerificationError("Request could not be completed.", status_code=400) from exc
    if not isinstance(parsed, Mapping):
        raise StripeWebhookVerificationError("Request could not be completed.", status_code=400)
    return {str(key): value for key, value in parsed.items()}


def _construct_event_with_sdk(
    *,
    raw_body: bytes,
    signature_header: str,
    webhook_secret: str,
    tolerance_seconds: int,
) -> dict[str, Any]:
    stripe = _stripe_module()
    event = stripe.Webhook.construct_event(
        raw_body,
        signature_header,
        webhook_secret,
        tolerance=tolerance_seconds,
    )
    return _event_mapping(event)


def verify_stripe_webhook_signature(
    *,
    raw_body: bytes | bytearray | memoryview | None = None,
    payload: bytes | bytearray | memoryview | None = None,
    signature_header: str | None = None,
    stripe_signature: str | None = None,
    sig_header: str | None = None,
    webhook_secret: str | None = None,
    secret: str | None = None,
    tolerance_seconds: int | None = None,
    tolerance: int | None = None,
    now: int | float | None = None,
    current_timestamp: int | float | None = None,
    require_supported_api_version: bool = True,
) -> dict[str, Any]:
    """Verify exact raw-body Stripe signature and return the event mapping.

    When ``now``/``current_timestamp`` is supplied, verification uses the local
    deterministic HMAC path because stripe-python does not expose a current-time
    override. Otherwise the SDK ``Webhook.construct_event`` path is attempted
    first, matching Stripe's documented runtime behavior.
    """

    body = _ensure_raw_body(raw_body if raw_body is not None else payload)
    signature = signature_header or stripe_signature or sig_header
    signing_secret = webhook_secret or secret
    if not signing_secret:
        raise StripeWebhookVerificationError("Request could not be completed.", status_code=503)
    tolerance_value = int(
        tolerance_seconds
        if tolerance_seconds is not None
        else tolerance
        if tolerance is not None
        else DEFAULT_STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS
    )
    comparison_now = now if now is not None else current_timestamp

    if comparison_now is None:
        try:
            event = _construct_event_with_sdk(
                raw_body=body,
                signature_header=str(signature or ""),
                webhook_secret=signing_secret,
                tolerance_seconds=tolerance_value,
            )
        except Exception as exc:
            raise StripeWebhookVerificationError("Request could not be completed.") from exc
    else:
        if not verify_stripe_signature_header(
            raw_body=body,
            signature_header=signature,
            webhook_secret=signing_secret,
            tolerance_seconds=tolerance_value,
            now=comparison_now,
        ):
            raise StripeWebhookVerificationError("Request could not be completed.")
        event = _parse_json_event(body)

    if require_supported_api_version:
        api_version = str(event.get("api_version") or "").strip()
        if api_version and api_version != SUPPORTED_STRIPE_API_VERSION:
            raise StripeFlowError(
                error_code=ErrorCode.STRIPE_API_VERSION_MISMATCH,
                status_code=503,
            )
    return event


def construct_verified_stripe_event(**kwargs: Any) -> dict[str, Any]:
    return verify_stripe_webhook_signature(**kwargs)


def construct_event(**kwargs: Any) -> dict[str, Any]:
    return verify_stripe_webhook_signature(**kwargs)


def verify_webhook_event(**kwargs: Any) -> dict[str, Any]:
    return verify_stripe_webhook_signature(**kwargs)


def extract_stripe_event_envelope(event: Mapping[str, Any]) -> dict[str, Any]:
    event_type = str(event.get("type") or "").strip()
    event_id = str(event.get("id") or "").strip()
    data = event.get("data") if isinstance(event.get("data"), Mapping) else {}
    obj = data.get("object") if isinstance(data, Mapping) and isinstance(data.get("object"), Mapping) else {}
    return {
        "id": event_id,
        "type": event_type,
        "api_version": event.get("api_version"),
        "created": event.get("created"),
        "object": obj,
        "allowed": event_type in constants.STRIPE_MVP_ALLOWED_WEBHOOK_EVENTS,
    }


def build_verified_provider_event(
    *,
    raw_body: bytes | bytearray | memoryview,
    signature_header: str | None,
    webhook_secret: str,
    event_hmac_secret: str | bytes,
    tolerance_seconds: int = DEFAULT_STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS,
    now: int | float | None = None,
) -> VerifiedProviderEvent:
    body = _ensure_raw_body(raw_body)
    event = verify_stripe_webhook_signature(
        raw_body=body,
        signature_header=signature_header,
        webhook_secret=webhook_secret,
        tolerance_seconds=tolerance_seconds,
        now=now,
    )
    envelope = extract_stripe_event_envelope(event)
    event_id = str(envelope["id"] or "")
    if not event_id:
        raise StripeWebhookVerificationError("Request could not be completed.", status_code=400)
    digest = webhook_event_id_hmac(provider="stripe", event_id=event_id, secret=event_hmac_secret)
    return VerifiedProviderEvent(
        provider="stripe",
        event_type=str(envelope["type"] or ""),
        event_id_hmac=digest,
        event_id_fingerprint=fingerprint_from_digest(digest),
        raw_body_sha256=raw_body_sha256(body),
        received_at=datetime.now(timezone.utc).replace(microsecond=0),
        payload=event,
    )


def verify_runtime_ready_for_webhook(*, env: Mapping[str, str] | None = None) -> bool:
    cfg = load_stripe_config(env=env)
    readiness = validate_stripe_runtime_readiness(cfg)
    return bool(readiness.ready or (cfg.webhooks_enabled and not readiness.critical_mismatches and not readiness.missing))


__all__ = [
    "StripeWebhookVerificationError",
    "build_verified_provider_event",
    "construct_event",
    "construct_verified_stripe_event",
    "extract_stripe_event_envelope",
    "verify_runtime_ready_for_webhook",
    "verify_stripe_webhook_signature",
    "verify_webhook_event",
]
