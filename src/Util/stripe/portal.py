"""Stripe Customer Portal session helpers for the MVP-limited flow.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.7.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

from src.Util.billing.idempotency import derive_stripe_api_idempotency_key
from src.Util.billing.provider import BillingCustomerOperationalRef, BillingHostedSession
from src.Util.billing.security import decrypt_provider_ref
from src.Util.error_handler import ErrorCode, StripeFlowError
from src.Util.stripe.client import StripeBillingClient


class StripePortalConfigurationError(StripeFlowError):
    def __init__(self, message: str | None = None) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.STRIPE_PORTAL_CONFIGURATION_INVALID,
            status_code=503,
        )


class StripePortalError(StripeFlowError):
    def __init__(self, message: str | None = None, *, status_code: int | None = None) -> None:
        super().__init__(
            message=message,
            error_code=ErrorCode.STRIPE_PORTAL_UNAVAILABLE,
            status_code=status_code or 503,
        )


def _new_ref(prefix: str = "bpo") -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def validate_restricted_portal_configuration(configuration: Mapping[str, Any] | Any) -> bool:
    """Validate Portal config allows only cancellation/payment-method updates.

    The MVP explicitly forbids Portal subscription updates, plan changes,
    upgrades, downgrades, and subscription item changes.
    """

    if not isinstance(configuration, Mapping):
        raise StripePortalConfigurationError("Billing service is not available.")
    features = configuration.get("features")
    if not isinstance(features, Mapping):
        raise StripePortalConfigurationError("Billing service is not available.")
    subscription_update = features.get("subscription_update")
    if isinstance(subscription_update, Mapping) and bool(subscription_update.get("enabled")):
        raise StripePortalConfigurationError("Billing service is not available.")
    # Payment method update and subscription cancel are permitted. Missing or
    # disabled permitted features should fail closed because operators must prove
    # the intended MVP configuration before enabling Portal.
    payment_method_update = features.get("payment_method_update")
    subscription_cancel = features.get("subscription_cancel")
    if not (isinstance(payment_method_update, Mapping) and bool(payment_method_update.get("enabled"))):
        raise StripePortalConfigurationError("Billing service is not available.")
    if not (isinstance(subscription_cancel, Mapping) and bool(subscription_cancel.get("enabled"))):
        raise StripePortalConfigurationError("Billing service is not available.")
    return True


def assert_portal_plan_changes_disabled(configuration: Mapping[str, Any] | Any) -> bool:
    return validate_restricted_portal_configuration(configuration)


def create_portal_session(
    *,
    customer: BillingCustomerOperationalRef,
    return_url: str,
    idempotency_key: str | None = None,
    portal_ref: str | None = None,
    configuration_id: str,
    client: StripeBillingClient,
    decryption_keys_by_id: Mapping[str, str | bytes],
    portal_configuration: Mapping[str, Any] | None = None,
) -> BillingHostedSession:
    try:
        if portal_configuration is None:
            portal_configuration = client.retrieve_portal_configuration(configuration_id)
        validate_restricted_portal_configuration(portal_configuration)
        stripe_customer_id = decrypt_provider_ref(encrypted_ref=customer, keys_by_id=decryption_keys_by_id)
        safe_portal_ref = portal_ref or _new_ref()
        provider_idempotency_key = idempotency_key or derive_stripe_api_idempotency_key(
            internal_ref=safe_portal_ref,
            operation="portal_session_create",
        )
        session = client.create_portal_session(
            params={
                "customer": stripe_customer_id,
                "configuration": configuration_id,
                "return_url": return_url,
            },
            idempotency_key=provider_idempotency_key,
        )
    except StripeFlowError:
        raise
    except Exception as exc:
        raise StripePortalError("Billing service is not available.") from exc
    url = _clean_text(session.get("url"))
    if not url:
        raise StripePortalError("Billing service is not available.")
    return BillingHostedSession(
        provider="stripe",
        url=url,
        hosted_ref=safe_portal_ref,
        portal_ref=safe_portal_ref,
        safe_metadata={"portal_ref": safe_portal_ref, "contract_version": 2},
    )


__all__ = [
    "StripePortalConfigurationError",
    "StripePortalError",
    "assert_portal_plan_changes_disabled",
    "create_portal_session",
    "validate_restricted_portal_configuration",
]
