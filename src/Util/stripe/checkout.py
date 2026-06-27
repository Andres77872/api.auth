"""Stripe Checkout Session creation from consumer-owned S2S intent.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.6.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from src.Util.billing.idempotency import derive_stripe_api_idempotency_key
from src.Util.billing.provider import BillingCheckoutIntent, BillingCustomerOperationalRef, BillingHostedSession
from src.Util.billing.redaction import redact_billing_sensitive_data
from src.Util.billing.security import decrypt_provider_ref
from src.Util.error_handler import ErrorCode, StripeFlowError
from src.Util.stripe.client import StripeBillingClient
from src.Util.stripe.config import StripeConfig


class StripeCheckoutError(StripeFlowError):
    def __init__(self, message: str | None = None, *, status_code: int | None = None) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.STRIPE_CHECKOUT_UNAVAILABLE,
            status_code=status_code or 503,
        )


def _new_ref(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def build_checkout_metadata(intent: BillingCheckoutIntent) -> dict[str, str]:
    """Return Stripe metadata containing only opaque/internal-safe evidence."""

    checkout_ref = intent.checkout_ref or _new_ref("bco")
    purchase_ref = intent.purchase_ref if intent.intent_type == "credit_purchase" else None
    subscription_ref = intent.subscription_ref if intent.intent_type == "subscription" else None
    metadata: dict[str, str] = {
        "api_auth_provider": "stripe",
        "api_auth_customer_ref": _clean_text(intent.safe_metadata.get("customer_ref")) or "",
        "api_auth_checkout_ref": checkout_ref,
        "api_auth_intent_type": intent.intent_type,
        "billing_contract_version": "2",
        "user_hash": intent.user_hash,
        "project_hash": intent.project_hash,
    }
    optional = {
        "api_auth_purchase_ref": purchase_ref,
        "api_auth_subscription_ref": subscription_ref,
        "consumer_plan_code": intent.plan_code,
        "consumer_tier_code": intent.tier_code,
        "consumer_tier_name": intent.tier_name,
        "consumer_credit_product_code": intent.credit_product_code,
    }
    for key, value in optional.items():
        cleaned = _clean_text(value)
        if cleaned:
            metadata[key] = cleaned
    redacted = redact_billing_sensitive_data(metadata)
    return {str(key): str(value) for key, value in redacted.items() if str(value)} if isinstance(redacted, Mapping) else metadata


def _line_item_for_price_ref(intent: BillingCheckoutIntent, *, resolved_price_id: str | None = None) -> dict[str, Any]:
    ref_type = str(intent.price_ref.ref_type or "").strip().lower()
    quantity = max(1, int(intent.quantity or 1))
    if ref_type == "price_id":
        return {"price": intent.price_ref.value, "quantity": quantity}
    if ref_type == "lookup_key" and resolved_price_id:
        return {"price": resolved_price_id, "quantity": quantity}
    raise StripeCheckoutError("Billing service is not available.")


def resolve_price_id_for_checkout(intent: BillingCheckoutIntent, *, client: StripeBillingClient) -> str:
    if str(intent.price_ref.ref_type).strip().lower() == "price_id":
        return intent.price_ref.value
    prices = client.list_prices_by_lookup_key(intent.price_ref.value)
    if not prices:
        raise StripeCheckoutError("Billing service is not available.")
    price_id = _clean_text(prices[0].get("id"))
    if not price_id:
        raise StripeCheckoutError("Billing service is not available.")
    return price_id


def build_checkout_session_params(
    *,
    intent: BillingCheckoutIntent,
    stripe_customer_id: str,
    resolved_price_id: str,
) -> dict[str, Any]:
    if intent.intent_type not in {"subscription", "credit_purchase"}:
        raise StripeCheckoutError("Billing request could not be completed.", status_code=422)
    mode = "subscription" if intent.intent_type == "subscription" else "payment"
    if mode == "subscription" and not (intent.plan_code and intent.tier_code):
        raise StripeCheckoutError("Billing request could not be completed.", status_code=422)
    if mode == "payment" and not intent.credit_product_code:
        raise StripeCheckoutError("Billing request could not be completed.", status_code=422)
    if not intent.success_url or not intent.cancel_url:
        raise StripeCheckoutError("Billing request could not be completed.", status_code=422)
    metadata = build_checkout_metadata(intent)
    return {
        "mode": mode,
        "customer": stripe_customer_id,
        "line_items": [_line_item_for_price_ref(intent, resolved_price_id=resolved_price_id)],
        "success_url": intent.success_url,
        "cancel_url": intent.cancel_url,
        "client_reference_id": intent.checkout_ref or metadata.get("api_auth_checkout_ref"),
        "metadata": metadata,
    }


def create_checkout_session(
    *,
    intent: BillingCheckoutIntent,
    customer: BillingCustomerOperationalRef,
    idempotency_key: str | None = None,
    client: StripeBillingClient,
    decryption_keys_by_id: Mapping[str, str | bytes],
) -> BillingHostedSession:
    """Create a Stripe Checkout Session and return only URL + opaque refs."""

    try:
        stripe_customer_id = decrypt_provider_ref(
            encrypted_ref=customer,
            keys_by_id=decryption_keys_by_id,
        )
        price_id = resolve_price_id_for_checkout(intent, client=client)
        checkout_ref = intent.checkout_ref or _new_ref("bco")
        normalized_intent = BillingCheckoutIntent(**{**intent.__dict__, "checkout_ref": checkout_ref})
        params = build_checkout_session_params(
            intent=normalized_intent,
            stripe_customer_id=stripe_customer_id,
            resolved_price_id=price_id,
        )
        provider_idempotency_key = idempotency_key or derive_stripe_api_idempotency_key(
            internal_ref=checkout_ref,
            operation="checkout_session_create",
        )
        session = client.create_checkout_session(params=params, idempotency_key=provider_idempotency_key)
    except StripeFlowError:
        raise
    except Exception as exc:
        raise StripeCheckoutError("Billing service is not available.") from exc

    url = _clean_text(session.get("url"))
    if not url:
        raise StripeCheckoutError("Billing service is not available.")
    return BillingHostedSession(
        provider="stripe",
        url=url,
        hosted_ref=checkout_ref,
        checkout_ref=checkout_ref,
        purchase_ref=normalized_intent.purchase_ref,
        subscription_ref=normalized_intent.subscription_ref,
        safe_metadata={
            "checkout_ref": checkout_ref,
            "provider_checkout_session_id": _clean_text(session.get("id")),
            "contract_version": 2,
        },
    )


def create_checkout_session_from_config(
    *,
    intent: BillingCheckoutIntent,
    customer: BillingCustomerOperationalRef,
    config: StripeConfig,
    decryption_keys_by_id: Mapping[str, str | bytes],
    stripe_client: Any | None = None,
) -> BillingHostedSession:
    client = StripeBillingClient.from_config(config, stripe_client=stripe_client)
    return create_checkout_session(
        intent=intent,
        customer=customer,
        client=client,
        decryption_keys_by_id=decryption_keys_by_id,
    )


__all__ = [
    "StripeCheckoutError",
    "build_checkout_metadata",
    "build_checkout_session_params",
    "create_checkout_session",
    "create_checkout_session_from_config",
    "resolve_price_id_for_checkout",
]
