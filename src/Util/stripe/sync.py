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


# Preference when one customer has several subscriptions: the one that is live, newest first.
_SUBSCRIPTION_STATUS_PREFERENCE = ("active", "trialing", "past_due", "unpaid", "paused", "incomplete")
_USER_LEVEL_JOB_TYPES = frozenset({"webhook_resync", "customer"})


def select_current_subscription(subscriptions: list[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """Pick the subscription a user-level resync should reflect: live over ended, newest first."""

    def _rank(item: Mapping[str, Any]) -> tuple[int, int]:
        status = str(item.get("status") or "").strip().lower()
        preference = _SUBSCRIPTION_STATUS_PREFERENCE.index(status) if status in _SUBSCRIPTION_STATUS_PREFERENCE else len(_SUBSCRIPTION_STATUS_PREFERENCE)
        try:
            created = int(item.get("created") or 0)
        except (TypeError, ValueError):
            created = 0
        return preference, -created

    candidates = [item for item in subscriptions or [] if isinstance(item, Mapping)]
    return min(candidates, key=_rank) if candidates else None


def _latest_charge_id(payment_intent: Mapping[str, Any]) -> str | None:
    latest = payment_intent.get("latest_charge")
    if isinstance(latest, Mapping):
        latest = latest.get("id")
    text = str(latest or "").strip()
    return text or None


def _fetched(job: BillingSyncJob, result: StripeSourceOfTruthResult, *, fetched_by: str) -> BillingSyncResult:
    return BillingSyncResult(
        provider="stripe",
        job_id=job.job_id,
        status="completed",
        safe_metadata=_safe_metadata(result.safe_metadata, fetched_by=fetched_by),
        object_type=result.object_type,
        provider_object=dict(result.payload),
    )


def _fetch_purchase(job: BillingSyncJob, refs: Mapping[str, Any], *, client: StripeBillingClient, keys: Mapping[str, str | bytes]) -> BillingSyncResult | None:
    if refs.get("charge") is not None:
        result = retrieve_charge_source_of_truth(encrypted_charge_ref=refs["charge"], client=client, decryption_keys_by_id=keys)
        return _fetched(job, result, fetched_by="charge_ref")
    if refs.get("payment_intent") is not None:
        result = retrieve_payment_intent_source_of_truth(encrypted_payment_intent_ref=refs["payment_intent"], client=client, decryption_keys_by_id=keys)
        latest_charge_id = _latest_charge_id(result.payload)
        if latest_charge_id:
            # The charge carries refund and dispute state; the payment intent does not.
            charge = client.retrieve_charge(latest_charge_id)
            return _fetched(
                job,
                StripeSourceOfTruthResult(object_type="charge", safe_metadata=_safe_metadata(status=charge.get("status")), payload=charge),
                fetched_by="payment_intent_ref",
            )
        return _fetched(job, result, fetched_by="payment_intent_ref")
    return None


def _fetch_customer_subscription(job: BillingSyncJob, encrypted_customer_ref: Any, *, client: StripeBillingClient, keys: Mapping[str, str | bytes]) -> BillingSyncResult:
    raw_customer_id = _decrypt_ref(encrypted_customer_ref, decryption_keys_by_id=keys)
    selected = select_current_subscription(client.list_customer_subscriptions(raw_customer_id))
    if selected is None:
        return BillingSyncResult(provider="stripe", job_id=job.job_id, status="completed", reason="no_provider_subscription")
    return _fetched(
        job,
        StripeSourceOfTruthResult(object_type="subscription", safe_metadata=_safe_metadata(status=selected.get("status")), payload=selected),
        fetched_by="customer_listing",
    )


def source_of_truth_resync(
    *,
    job: BillingSyncJob,
    client: StripeBillingClient | None = None,
    operational_refs: Mapping[str, Any] | None = None,
    decryption_keys_by_id: Mapping[str, str | bytes] | None = None,
) -> BillingSyncResult:
    """Fetch the Stripe object a claimed sync job is about; the worker writes it back.

    Typed jobs fetch their own object (a subscription job its subscription, a purchase job
    its charge or payment intent) and fail when its ref is missing. User-level jobs (a
    resync requested through the S2S route, or a webhook that could not be classified)
    list the user's customer's subscriptions and pick the current one; with no customer
    and no subscription on record there is nothing to repair and the job completes.
    The fetched object rides on the result (``provider_object``) and is never serialized.
    """

    if client is None and not job.billing_group_id:
        return BillingSyncResult(provider="stripe", job_id=job.job_id, status="failed", retryable=False, reason="missing_billing_group_id")
    if client is None:
        return BillingSyncResult(provider="stripe", job_id=job.job_id, status="failed", retryable=True, reason="stripe_client_not_ready")
    refs = operational_refs or {}
    keys = decryption_keys_by_id or {}
    try:
        if job.job_type == "purchase":
            fetched = _fetch_purchase(job, refs, client=client, keys=keys)
            if fetched is not None:
                return fetched
        elif job.job_type == "subscription" and refs.get("subscription") is not None:
            result = retrieve_subscription_source_of_truth(encrypted_subscription_ref=refs["subscription"], client=client, decryption_keys_by_id=keys)
            return _fetched(job, result, fetched_by="subscription_ref")
        elif job.job_type in _USER_LEVEL_JOB_TYPES:
            if job.purchase_id:
                fetched = _fetch_purchase(job, refs, client=client, keys=keys)
                if fetched is not None:
                    return fetched
            if refs.get("customer") is not None:
                return _fetch_customer_subscription(job, refs["customer"], client=client, keys=keys)
            if refs.get("subscription") is not None:
                result = retrieve_subscription_source_of_truth(encrypted_subscription_ref=refs["subscription"], client=client, decryption_keys_by_id=keys)
                return _fetched(job, result, fetched_by="subscription_ref")
            return BillingSyncResult(provider="stripe", job_id=job.job_id, status="completed", reason="no_provider_refs")
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


__all__ = [
    "StripeSourceOfTruthResult",
    "StripeSyncError",
    "retrieve_charge_source_of_truth",
    "retrieve_customer_source_of_truth",
    "retrieve_dispute_source_of_truth",
    "retrieve_payment_intent_source_of_truth",
    "retrieve_subscription_source_of_truth",
    "select_current_subscription",
    "source_of_truth_resync",
]
