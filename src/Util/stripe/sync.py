"""Stripe source-of-truth resync helper seams.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.10.

This module performs provider-fact retrieval only. It does not call consumers,
does not mutate product credit ledgers, and does not expose raw Stripe IDs in
result metadata.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from src.Util.billing.provider import BillingSyncJob, BillingSyncResult
from src.Util.billing.redaction import redact_billing_sensitive_data, sanitize_billing_sensitive_text
from src.Util.billing.security import decrypt_provider_ref
from src.Util.stripe.client import StripeAPIError, StripeBillingClient


class StripeSyncError(RuntimeError):
    """Raised for invalid Stripe source-of-truth resync inputs."""


@dataclass(frozen=True)
class StripeSourceOfTruthResult:
    provider: str = "stripe"
    object_type: str = "unknown"
    status: str = "retrieved"
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)
    payload: Mapping[str, Any] = field(default_factory=dict, repr=False)


def _safe_metadata(metadata: Mapping[str, Any] | None = None, **extra: Any) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    if metadata:
        merged.update({str(key): value for key, value in metadata.items()})
    for key, value in extra.items():
        if value is not None:
            merged[key] = value
    redacted = redact_billing_sensitive_data(merged)
    return redacted if isinstance(redacted, dict) else {}


def _decrypt_ref(encrypted_ref: Any, *, decryption_keys_by_id: Mapping[str, str | bytes]) -> str:
    return decrypt_provider_ref(encrypted_ref=encrypted_ref, keys_by_id=decryption_keys_by_id)


def retrieve_customer_source_of_truth(*, encrypted_customer_ref: Any, client: StripeBillingClient, decryption_keys_by_id: Mapping[str, str | bytes]) -> StripeSourceOfTruthResult:
    raw_customer_id = _decrypt_ref(encrypted_customer_ref, decryption_keys_by_id=decryption_keys_by_id)
    payload = client.retrieve_customer(raw_customer_id)
    return StripeSourceOfTruthResult(object_type="customer", safe_metadata=_safe_metadata(status=payload.get("object")), payload=payload)


def retrieve_subscription_source_of_truth(*, encrypted_subscription_ref: Any, client: StripeBillingClient, decryption_keys_by_id: Mapping[str, str | bytes]) -> StripeSourceOfTruthResult:
    raw_subscription_id = _decrypt_ref(encrypted_subscription_ref, decryption_keys_by_id=decryption_keys_by_id)
    payload = client.retrieve_subscription(raw_subscription_id)
    return StripeSourceOfTruthResult(object_type="subscription", safe_metadata=_safe_metadata(status=payload.get("status")), payload=payload)


def retrieve_payment_intent_source_of_truth(*, encrypted_payment_intent_ref: Any, client: StripeBillingClient, decryption_keys_by_id: Mapping[str, str | bytes]) -> StripeSourceOfTruthResult:
    raw_payment_intent_id = _decrypt_ref(encrypted_payment_intent_ref, decryption_keys_by_id=decryption_keys_by_id)
    payload = client.retrieve_payment_intent(raw_payment_intent_id)
    return StripeSourceOfTruthResult(object_type="payment_intent", safe_metadata=_safe_metadata(status=payload.get("status")), payload=payload)


def retrieve_charge_source_of_truth(*, encrypted_charge_ref: Any, client: StripeBillingClient, decryption_keys_by_id: Mapping[str, str | bytes]) -> StripeSourceOfTruthResult:
    raw_charge_id = _decrypt_ref(encrypted_charge_ref, decryption_keys_by_id=decryption_keys_by_id)
    payload = client.retrieve_charge(raw_charge_id)
    return StripeSourceOfTruthResult(object_type="charge", safe_metadata=_safe_metadata(status=payload.get("status"), refunded=payload.get("refunded")), payload=payload)


def retrieve_dispute_source_of_truth(*, encrypted_dispute_ref: Any, client: StripeBillingClient, decryption_keys_by_id: Mapping[str, str | bytes]) -> StripeSourceOfTruthResult:
    raw_dispute_id = _decrypt_ref(encrypted_dispute_ref, decryption_keys_by_id=decryption_keys_by_id)
    payload = client.retrieve_dispute(raw_dispute_id)
    return StripeSourceOfTruthResult(object_type="dispute", safe_metadata=_safe_metadata(status=payload.get("status")), payload=payload)


def source_of_truth_resync(
    *,
    job: BillingSyncJob,
    client: StripeBillingClient | None = None,
    operational_refs: Mapping[str, Any] | None = None,
    decryption_keys_by_id: Mapping[str, str | bytes] | None = None,
) -> BillingSyncResult:
    """Dispatch a claimed sync job to an injected source-of-truth retrieval seam.

    Phase 8 worker code owns DB job claiming and persistence. Phase 6 provides
    the provider adapter seam and fail-closed, redacted result modeling.
    """

    if client is None and not job.billing_group_id:
        return BillingSyncResult(provider="stripe", job_id=job.job_id, status="failed", retryable=False, reason="missing_billing_group_id")
    if client is None:
        return BillingSyncResult(provider="stripe", job_id=job.job_id, status="failed", retryable=True, reason="stripe_client_not_ready")
    refs = operational_refs or {}
    keys = decryption_keys_by_id or {}
    try:
        if job.job_type == "customer" and refs.get("customer") is not None:
            result = retrieve_customer_source_of_truth(encrypted_customer_ref=refs["customer"], client=client, decryption_keys_by_id=keys)
        elif job.job_type == "subscription" and refs.get("subscription") is not None:
            result = retrieve_subscription_source_of_truth(encrypted_subscription_ref=refs["subscription"], client=client, decryption_keys_by_id=keys)
        elif job.job_type == "purchase" and refs.get("charge") is not None:
            result = retrieve_charge_source_of_truth(encrypted_charge_ref=refs["charge"], client=client, decryption_keys_by_id=keys)
        elif job.job_type == "purchase" and refs.get("payment_intent") is not None:
            result = retrieve_payment_intent_source_of_truth(encrypted_payment_intent_ref=refs["payment_intent"], client=client, decryption_keys_by_id=keys)
        elif job.job_type == "webhook_resync" and refs.get("subscription") is not None:
            result = retrieve_subscription_source_of_truth(encrypted_subscription_ref=refs["subscription"], client=client, decryption_keys_by_id=keys)
        elif job.job_type == "webhook_resync" and refs.get("charge") is not None:
            result = retrieve_charge_source_of_truth(encrypted_charge_ref=refs["charge"], client=client, decryption_keys_by_id=keys)
        elif job.job_type == "webhook_resync" and refs.get("payment_intent") is not None:
            result = retrieve_payment_intent_source_of_truth(encrypted_payment_intent_ref=refs["payment_intent"], client=client, decryption_keys_by_id=keys)
        elif job.job_type == "webhook_resync" and refs.get("customer") is not None:
            result = retrieve_customer_source_of_truth(encrypted_customer_ref=refs["customer"], client=client, decryption_keys_by_id=keys)
        else:
            return BillingSyncResult(provider="stripe", job_id=job.job_id, status="failed", retryable=False, reason="missing_operational_ref")
    except StripeAPIError as exc:
        return BillingSyncResult(
            provider="stripe",
            job_id=job.job_id,
            status="retry",
            retry_after_seconds=exc.retry_after_seconds,
            retryable=True,
            reason="provider_api_failure",
            safe_metadata=_safe_metadata(error=sanitize_billing_sensitive_text(str(exc))),
        )
    except Exception as exc:
        return BillingSyncResult(
            provider="stripe",
            job_id=job.job_id,
            status="retry",
            retryable=True,
            reason="provider_or_decrypt_failure",
            safe_metadata=_safe_metadata(error=sanitize_billing_sensitive_text(str(exc))),
        )
    return BillingSyncResult(provider="stripe", job_id=job.job_id, status="completed", safe_metadata=result.safe_metadata)


__all__ = [
    "StripeSourceOfTruthResult",
    "StripeSyncError",
    "retrieve_charge_source_of_truth",
    "retrieve_customer_source_of_truth",
    "retrieve_dispute_source_of_truth",
    "retrieve_payment_intent_source_of_truth",
    "retrieve_subscription_source_of_truth",
    "source_of_truth_resync",
]
