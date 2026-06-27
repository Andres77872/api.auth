"""Stripe event classification into normalized provider billing facts.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.9.

The classifier is pure: no network, database, Redis, or environment reads. It
maps approved Stripe event payloads to normalized subscription/purchase fact
statuses and never decides product benefits or credit-ledger mutations.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from src.Util import auth_constants as constants
from src.Util.billing.provider import BillingClassificationResult, VerifiedProviderEvent
from src.Util.billing.status import (
    PURCHASE_STATUS_DISPUTED,
    PURCHASE_STATUS_DISPUTE_LOST,
    PURCHASE_STATUS_DISPUTE_WON,
    PURCHASE_STATUS_PAID,
    PURCHASE_STATUS_PARTIALLY_REFUNDED,
    PURCHASE_STATUS_REFUNDED,
    PURCHASE_STATUS_UNKNOWN,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_CANCELED,
    SUBSCRIPTION_STATUS_INCOMPLETE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_PAUSED,
    SUBSCRIPTION_STATUS_PENDING,
    SUBSCRIPTION_STATUS_STALE,
    SUBSCRIPTION_STATUS_TRIALING,
    SUBSCRIPTION_STATUS_UNKNOWN,
    SUBSCRIPTION_STATUS_UNPAID,
    normalize_subscription_status,
)
from src.Util.billing.redaction import redact_billing_sensitive_data


CLASSIFICATION_VERSION = 2
APPROVED_EVENT_TYPES = frozenset(constants.STRIPE_MVP_ALLOWED_WEBHOOK_EVENTS)


class StripeClassificationError(ValueError):
    """Raised for malformed caller inputs, never for provider state."""


def _plain_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, VerifiedProviderEvent):
        return dict(value.payload)
    if isinstance(value, Mapping):
        return {str(key): item for key, item in value.items()}
    if is_dataclass(value):
        return {str(key): item for key, item in asdict(value).items()}
    if hasattr(value, "to_dict_recursive") and callable(value.to_dict_recursive):
        result = value.to_dict_recursive()
        if isinstance(result, Mapping):
            return {str(key): item for key, item in result.items()}
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, Mapping):
            return {str(key): item for key, item in result.items()}
    return {}


def _event_object(event: Mapping[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    if isinstance(data, Mapping) and isinstance(data.get("object"), Mapping):
        return {str(key): value for key, value in data["object"].items()}
    if isinstance(event.get("object"), Mapping):
        return {str(key): value for key, value in event["object"].items()}
    return {}


def _metadata(obj: Mapping[str, Any]) -> dict[str, str]:
    meta = obj.get("metadata")
    if not isinstance(meta, Mapping):
        return {}
    return {str(key): str(value) for key, value in meta.items() if value is not None}


def _safe_metadata(obj: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    metadata = _metadata(obj)
    allowed_keys = {
        "user_hash",
        "project_hash",
        "plan_code",
        "tier_code",
        "tier_name",
        "credit_product_code",
        "checkout_ref",
        "purchase_ref",
        "subscription_ref",
        "client_intent_ref",
    }
    safe: dict[str, Any] = {key: metadata[key] for key in allowed_keys if key in metadata}
    for key, value in extra.items():
        if value is not None:
            safe[key] = value
    redacted = redact_billing_sensitive_data(safe)
    return redacted if isinstance(redacted, dict) else {}


def _utc_from_epoch(value: Any) -> str | None:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).replace(microsecond=0).isoformat()


def _first_price_lookup_key(subscription: Mapping[str, Any]) -> str | None:
    items = subscription.get("items")
    data = items.get("data") if isinstance(items, Mapping) else None
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, Mapping):
        return None
    price = first.get("price")
    if not isinstance(price, Mapping):
        return None
    lookup_key = price.get("lookup_key")
    return str(lookup_key).strip() if lookup_key else None


def _evidence_mismatch(subscription: Mapping[str, Any]) -> bool:
    metadata = _metadata(subscription)
    plan_code = metadata.get("plan_code") or metadata.get("consumer_plan_code")
    lookup_key = _first_price_lookup_key(subscription)
    if not plan_code or not lookup_key:
        return False
    # Consumer-owned evidence is not canonical here; this only detects obvious
    # contradiction so api.auth fails closed instead of inventing product meaning.
    normalized_plan = plan_code.strip().lower().replace("-", "_")
    normalized_lookup = lookup_key.strip().lower().replace("-", "_")
    return normalized_plan not in normalized_lookup


def _subscription_result(
    *,
    event_type: str,
    status: str,
    obj: Mapping[str, Any],
    reason: str | None = None,
    resync_required: bool = False,
) -> BillingClassificationResult:
    return BillingClassificationResult(
        provider="stripe",
        event_type=event_type,
        subscription_status=status,
        resync_required=resync_required,
        reason=reason,
        safe_metadata=_safe_metadata(
            obj,
            current_period_end=_utc_from_epoch(obj.get("current_period_end")),
            trial_end=_utc_from_epoch(obj.get("trial_end")),
            cancel_at_period_end=bool(obj.get("cancel_at_period_end")),
            classification_version=CLASSIFICATION_VERSION,
        ),
    )


def _purchase_result(
    *,
    event_type: str,
    status: str,
    obj: Mapping[str, Any],
    reason: str | None = None,
    resync_required: bool = False,
) -> BillingClassificationResult:
    return BillingClassificationResult(
        provider="stripe",
        event_type=event_type,
        purchase_status=status,
        resync_required=resync_required,
        reason=reason,
        safe_metadata=_safe_metadata(
            obj,
            classification_version=CLASSIFICATION_VERSION,
        ),
    )


def _classify_checkout_completed(event_type: str, obj: Mapping[str, Any]) -> BillingClassificationResult:
    mode = str(obj.get("mode") or "").strip().lower()
    status = str(obj.get("status") or "").strip().lower()
    payment_status = str(obj.get("payment_status") or "").strip().lower()
    if mode == "payment":
        purchase_status = PURCHASE_STATUS_PAID if status == "complete" and payment_status == "paid" else PURCHASE_STATUS_UNKNOWN
        return _purchase_result(event_type=event_type, status=purchase_status, obj=obj, reason="checkout_payment_completed")
    if mode == "subscription":
        return _subscription_result(event_type=event_type, status=SUBSCRIPTION_STATUS_PENDING, obj=obj, reason="checkout_subscription_completed_pending_source_of_truth")
    return BillingClassificationResult(
        provider="stripe",
        event_type=event_type,
        subscription_status=SUBSCRIPTION_STATUS_UNKNOWN,
        purchase_status=None,
        resync_required=True,
        reason="checkout_completed_unknown_mode",
        safe_metadata={"classification_version": CLASSIFICATION_VERSION},
    )


def _classify_subscription_event(event_type: str, obj: Mapping[str, Any]) -> BillingClassificationResult:
    if _evidence_mismatch(obj):
        return _subscription_result(
            event_type=event_type,
            status=SUBSCRIPTION_STATUS_UNKNOWN,
            obj=obj,
            reason="label_or_price_evidence_mismatch",
            resync_required=True,
        )
    if event_type == "customer.subscription.deleted":
        return _subscription_result(event_type=event_type, status=SUBSCRIPTION_STATUS_CANCELED, obj=obj, reason="subscription_deleted")
    raw_status = str(obj.get("status") or "").strip().lower()
    mapping = {
        "incomplete": SUBSCRIPTION_STATUS_INCOMPLETE,
        "incomplete_expired": SUBSCRIPTION_STATUS_INCOMPLETE,
        "trialing": SUBSCRIPTION_STATUS_TRIALING,
        "active": SUBSCRIPTION_STATUS_ACTIVE,
        "past_due": SUBSCRIPTION_STATUS_PAST_DUE,
        "unpaid": SUBSCRIPTION_STATUS_UNPAID,
        "paused": SUBSCRIPTION_STATUS_PAUSED,
        "canceled": SUBSCRIPTION_STATUS_CANCELED,
    }
    normalized = mapping.get(raw_status, normalize_subscription_status(raw_status, default=SUBSCRIPTION_STATUS_UNKNOWN))
    return _subscription_result(event_type=event_type, status=normalized, obj=obj, reason=f"subscription_{normalized}")


def _classify_invoice_event(event_type: str, obj: Mapping[str, Any]) -> BillingClassificationResult:
    if event_type == "invoice.paid":
        return _subscription_result(event_type=event_type, status=SUBSCRIPTION_STATUS_ACTIVE, obj=obj, reason="invoice_paid_recovery")
    return _subscription_result(
        event_type=event_type,
        status=SUBSCRIPTION_STATUS_PAST_DUE,
        obj=obj,
        reason="invoice_payment_failed_resync_required",
        resync_required=True,
    )


def _classify_charge_refunded(event_type: str, obj: Mapping[str, Any]) -> BillingClassificationResult:
    try:
        amount = int(obj.get("amount") or 0)
        refunded_amount = int(obj.get("amount_refunded") or 0)
    except (TypeError, ValueError):
        amount = 0
        refunded_amount = 0
    fully_refunded = bool(obj.get("refunded")) or (amount > 0 and refunded_amount >= amount)
    status = PURCHASE_STATUS_REFUNDED if fully_refunded else PURCHASE_STATUS_PARTIALLY_REFUNDED
    return _purchase_result(event_type=event_type, status=status, obj=obj, reason="charge_refunded")


def _classify_dispute_event(event_type: str, obj: Mapping[str, Any]) -> BillingClassificationResult:
    if event_type == "charge.dispute.created":
        return _purchase_result(event_type=event_type, status=PURCHASE_STATUS_DISPUTED, obj=obj, reason="dispute_created")
    raw_status = str(obj.get("status") or "").strip().lower()
    if raw_status in {"won", "warning_closed"}:
        status = PURCHASE_STATUS_DISPUTE_WON
    elif raw_status in {"lost", "lost_evidence", "charge_refunded"}:
        status = PURCHASE_STATUS_DISPUTE_LOST
    else:
        status = PURCHASE_STATUS_UNKNOWN
    return _purchase_result(event_type=event_type, status=status, obj=obj, reason="dispute_closed")


def classify_stripe_event(
    *,
    event: Mapping[str, Any] | VerifiedProviderEvent | Any | None = None,
    stripe_event: Mapping[str, Any] | Any | None = None,
    payload: Mapping[str, Any] | Any | None = None,
) -> BillingClassificationResult:
    source = event if event is not None else stripe_event if stripe_event is not None else payload
    event_map = _plain_mapping(source)
    event_type = str(event_map.get("type") or "").strip()
    obj = _event_object(event_map)
    if not event_type:
        raise StripeClassificationError("Stripe event type is required")
    if event_type not in APPROVED_EVENT_TYPES:
        return BillingClassificationResult(
            provider="stripe",
            event_type=event_type,
            ignored=True,
            no_mutation=True,
            reason="unsupported_event_ignored_noop",
            safe_metadata={"classification_version": CLASSIFICATION_VERSION},
        )
    if event_type == "checkout.session.completed":
        return _classify_checkout_completed(event_type, obj)
    if event_type.startswith("customer.subscription."):
        return _classify_subscription_event(event_type, obj)
    if event_type.startswith("invoice."):
        return _classify_invoice_event(event_type, obj)
    if event_type == "charge.refunded":
        return _classify_charge_refunded(event_type, obj)
    if event_type.startswith("charge.dispute."):
        return _classify_dispute_event(event_type, obj)
    return BillingClassificationResult(
        provider="stripe",
        event_type=event_type,
        ignored=True,
        no_mutation=True,
        reason="allowed_event_without_mutation_handler",
        safe_metadata={"classification_version": CLASSIFICATION_VERSION},
    )


def classify_event(**kwargs: Any) -> BillingClassificationResult:
    return classify_stripe_event(**kwargs)


def classify_webhook_event(**kwargs: Any) -> BillingClassificationResult:
    return classify_stripe_event(**kwargs)


def classification_to_safe_dict(result: BillingClassificationResult) -> dict[str, Any]:
    return result.to_dict()


__all__ = [
    "APPROVED_EVENT_TYPES",
    "CLASSIFICATION_VERSION",
    "StripeClassificationError",
    "classification_to_safe_dict",
    "classify_event",
    "classify_stripe_event",
    "classify_webhook_event",
]
