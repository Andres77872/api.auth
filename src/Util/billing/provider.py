"""Provider adapter contracts for the generic billing boundary.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 4.4.

The protocol is intentionally small. Implementations may validate provider facts
and create provider-hosted sessions, but they must not issue local sessions,
JWTs, cookies, API keys, product mappings, or account-credit mutations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class ProviderReadiness:
    provider: str
    ready: bool
    status: str
    missing: tuple[str, ...] = ()
    degraded: tuple[str, ...] = ()
    capabilities: Mapping[str, bool] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "ready": self.ready,
            "status": self.status,
            "missing": list(self.missing),
            "degraded": list(self.degraded),
            "capabilities": dict(self.capabilities),
        }


@dataclass(frozen=True)
class BillingProviderPriceRef:
    ref_type: str
    value: str = field(repr=False)


@dataclass(frozen=True)
class BillingCheckoutIntent:
    user_id: str
    project_id: str
    user_hash: str
    project_hash: str
    provider: str
    intent_type: str
    price_ref: BillingProviderPriceRef = field(repr=False)
    quantity: int = 1
    checkout_ref: str | None = None
    purchase_ref: str | None = None
    subscription_ref: str | None = None
    plan_code: str | None = None
    tier_code: str | None = None
    tier_name: str | None = None
    credit_product_code: str | None = None
    success_url: str | None = field(default=None, repr=False)
    cancel_url: str | None = field(default=None, repr=False)
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BillingCustomerOperationalRef:
    provider: str
    customer_ref: str
    ciphertext: bytes = field(repr=False)
    key_id: str
    algorithm: str = "fernet-v1"


@dataclass(frozen=True)
class BillingHostedSession:
    provider: str
    url: str = field(repr=False)
    hosted_ref: str
    checkout_ref: str | None = None
    portal_ref: str | None = None
    purchase_ref: str | None = None
    subscription_ref: str | None = None
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)

    def safe_response(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "success": True,
            "url": self.url,
            "contract_version": 2,
        }
        for key in ("checkout_ref", "portal_ref", "purchase_ref", "subscription_ref"):
            value = getattr(self, key)
            if value is not None:
                result[key] = value
        return result


@dataclass(frozen=True)
class VerifiedProviderEvent:
    provider: str
    event_type: str
    event_id_hmac: bytes = field(repr=False)
    event_id_fingerprint: str
    raw_body_sha256: bytes = field(repr=False)
    received_at: datetime | None = None
    payload: Mapping[str, Any] = field(default_factory=dict, repr=False)


@dataclass(frozen=True)
class BillingClassificationResult:
    provider: str
    event_type: str | None = None
    ignored: bool = False
    no_mutation: bool = False
    subscription_status: str | None = None
    purchase_status: str | None = None
    resync_required: bool = False
    reason: str | None = None
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str | None:
        return self.subscription_status or self.purchase_status

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "event_type": self.event_type,
            "ignored": self.ignored,
            "no_mutation": self.no_mutation,
            "subscription_status": self.subscription_status,
            "purchase_status": self.purchase_status,
            "resync_required": self.resync_required,
            "reason": self.reason,
            "safe_metadata": dict(self.safe_metadata),
        }


@dataclass(frozen=True)
class BillingSyncJob:
    job_id: str
    provider: str
    job_type: str
    user_id: str | None = None
    project_id: str | None = None
    billing_group_id: str | None = None
    customer_id: str | None = None
    subscription_id: str | None = None
    purchase_id: str | None = None
    attempts: int = 0
    max_attempts: int = 8
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BillingSyncResult:
    provider: str
    job_id: str | None = None
    status: str = "completed"
    retry_after_seconds: int | None = None
    retryable: bool = False
    reason: str | None = None
    safe_metadata: Mapping[str, Any] = field(default_factory=dict)


@runtime_checkable
class BillingProviderAdapter(Protocol):
    provider: str

    def readiness(self) -> ProviderReadiness: ...

    async def create_checkout_session(
        self,
        *,
        intent: BillingCheckoutIntent,
        customer: BillingCustomerOperationalRef,
        idempotency_key: str,
    ) -> BillingHostedSession: ...

    async def create_portal_session(
        self,
        *,
        customer: BillingCustomerOperationalRef,
        return_url: str,
        idempotency_key: str,
    ) -> BillingHostedSession: ...

    async def verify_webhook_event(
        self,
        *,
        raw_body: bytes,
        signature_header: str | None,
    ) -> VerifiedProviderEvent: ...

    async def classify_event(
        self,
        *,
        event: VerifiedProviderEvent,
    ) -> BillingClassificationResult: ...

    async def source_of_truth_resync(
        self,
        *,
        job: BillingSyncJob,
    ) -> BillingSyncResult: ...


__all__ = [
    "BillingCheckoutIntent",
    "BillingClassificationResult",
    "BillingCustomerOperationalRef",
    "BillingHostedSession",
    "BillingProviderAdapter",
    "BillingProviderPriceRef",
    "BillingSyncJob",
    "BillingSyncResult",
    "ProviderReadiness",
    "VerifiedProviderEvent",
]
