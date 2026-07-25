"""Normalized provider-agnostic billing status helpers.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 4.2.

The helpers here model provider facts only. They intentionally do not define
membership definitions, product mappings, feature access, or account credits.
Consumers project these facts inside their own product domain.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


BILLING_CONTRACT_VERSION = 2

SUBSCRIPTION_STATUS_FREE = "free"
SUBSCRIPTION_STATUS_PENDING = "pending"
SUBSCRIPTION_STATUS_INCOMPLETE = "incomplete"
SUBSCRIPTION_STATUS_TRIALING = "trialing"
SUBSCRIPTION_STATUS_ACTIVE = "active"
SUBSCRIPTION_STATUS_PAST_DUE = "past_due"
SUBSCRIPTION_STATUS_UNPAID = "unpaid"
SUBSCRIPTION_STATUS_PAUSED = "paused"
SUBSCRIPTION_STATUS_CANCELED = "canceled"
SUBSCRIPTION_STATUS_FORMER = "former"
SUBSCRIPTION_STATUS_STALE = "stale"
SUBSCRIPTION_STATUS_UNKNOWN = "unknown"

NORMALIZED_SUBSCRIPTION_STATUSES = (
    SUBSCRIPTION_STATUS_FREE,
    SUBSCRIPTION_STATUS_PENDING,
    SUBSCRIPTION_STATUS_INCOMPLETE,
    SUBSCRIPTION_STATUS_TRIALING,
    SUBSCRIPTION_STATUS_ACTIVE,
    SUBSCRIPTION_STATUS_PAST_DUE,
    SUBSCRIPTION_STATUS_UNPAID,
    SUBSCRIPTION_STATUS_PAUSED,
    SUBSCRIPTION_STATUS_CANCELED,
    SUBSCRIPTION_STATUS_FORMER,
    SUBSCRIPTION_STATUS_STALE,
    SUBSCRIPTION_STATUS_UNKNOWN,
)
SUBSCRIPTION_STATUS_SET = frozenset(NORMALIZED_SUBSCRIPTION_STATUSES)

PURCHASE_STATUS_PENDING = "pending"
PURCHASE_STATUS_PAID = "paid"
PURCHASE_STATUS_REFUNDED = "refunded"
PURCHASE_STATUS_PARTIALLY_REFUNDED = "partially_refunded"
PURCHASE_STATUS_DISPUTED = "disputed"
PURCHASE_STATUS_DISPUTE_WON = "dispute_won"
PURCHASE_STATUS_DISPUTE_LOST = "dispute_lost"
PURCHASE_STATUS_STALE = "stale"
PURCHASE_STATUS_UNKNOWN = "unknown"

NORMALIZED_PURCHASE_STATUSES = (
    PURCHASE_STATUS_PENDING,
    PURCHASE_STATUS_PAID,
    PURCHASE_STATUS_REFUNDED,
    PURCHASE_STATUS_PARTIALLY_REFUNDED,
    PURCHASE_STATUS_DISPUTED,
    PURCHASE_STATUS_DISPUTE_WON,
    PURCHASE_STATUS_DISPUTE_LOST,
    PURCHASE_STATUS_STALE,
    PURCHASE_STATUS_UNKNOWN,
)
PURCHASE_STATUS_SET = frozenset(NORMALIZED_PURCHASE_STATUSES)

LINK_STATUS_NONE = "none"
LINK_STATUS_PENDING = "pending"
LINK_STATUS_LINKED = "linked"
LINK_STATUS_REVOKED = "revoked"
LINK_STATUS_STALE = "stale"

NORMALIZED_LINK_STATUSES = (
    LINK_STATUS_NONE,
    LINK_STATUS_PENDING,
    LINK_STATUS_LINKED,
    LINK_STATUS_REVOKED,
    LINK_STATUS_STALE,
)
LINK_STATUS_SET = frozenset(NORMALIZED_LINK_STATUSES)

CURRENT_PROVIDER_CONFIRMED_SUBSCRIPTION_STATUSES = frozenset(
    {SUBSCRIPTION_STATUS_TRIALING, SUBSCRIPTION_STATUS_ACTIVE}
)
NON_CURRENT_SUBSCRIPTION_STATUSES = frozenset(
    {
        SUBSCRIPTION_STATUS_FREE,
        SUBSCRIPTION_STATUS_PENDING,
        SUBSCRIPTION_STATUS_INCOMPLETE,
        SUBSCRIPTION_STATUS_PAST_DUE,
        SUBSCRIPTION_STATUS_UNPAID,
        SUBSCRIPTION_STATUS_PAUSED,
        SUBSCRIPTION_STATUS_CANCELED,
        SUBSCRIPTION_STATUS_FORMER,
        SUBSCRIPTION_STATUS_STALE,
        SUBSCRIPTION_STATUS_UNKNOWN,
    }
)
TERMINAL_SUBSCRIPTION_STATUSES = frozenset(
    {SUBSCRIPTION_STATUS_FREE, SUBSCRIPTION_STATUS_CANCELED, SUBSCRIPTION_STATUS_FORMER}
)
TERMINAL_PURCHASE_STATUSES = frozenset(
    {
        PURCHASE_STATUS_REFUNDED,
        PURCHASE_STATUS_DISPUTE_WON,
        PURCHASE_STATUS_DISPUTE_LOST,
    }
)

_SUBSCRIPTION_ALIASES = {
    "cancelled": SUBSCRIPTION_STATUS_CANCELED,
    "canceled_at_period_end": SUBSCRIPTION_STATUS_ACTIVE,
    "pastdue": SUBSCRIPTION_STATUS_PAST_DUE,
    "not_paid": SUBSCRIPTION_STATUS_UNPAID,
    "none": SUBSCRIPTION_STATUS_FREE,
}
_PURCHASE_ALIASES = {
    "complete": PURCHASE_STATUS_PAID,
    "completed": PURCHASE_STATUS_PAID,
    "succeeded": PURCHASE_STATUS_PAID,
    "partial_refund": PURCHASE_STATUS_PARTIALLY_REFUNDED,
    "partially_refund": PURCHASE_STATUS_PARTIALLY_REFUNDED,
    "chargeback": PURCHASE_STATUS_DISPUTED,
    "won": PURCHASE_STATUS_DISPUTE_WON,
    "lost": PURCHASE_STATUS_DISPUTE_LOST,
}
_LINK_ALIASES = {
    "unlinked": LINK_STATUS_NONE,
    "blocked": LINK_STATUS_REVOKED,
    "proof_required": LINK_STATUS_PENDING,
}


class BillingStatusError(ValueError):
    """Raised when billing status data cannot be normalized safely."""


@dataclass(frozen=True)
class SafeBillingStatus:
    """Safe provider-fact snapshot suitable for S2S serialization."""

    provider: str = "stripe"
    status: str = SUBSCRIPTION_STATUS_FREE
    plan_code: str = SUBSCRIPTION_STATUS_FREE
    tier_code: str | None = None
    tier_name: str | None = None
    link_status: str = LINK_STATUS_NONE
    current_period_end: datetime | None = None
    cancel_at_period_end: bool = False
    trial_end: datetime | None = None
    grace_period_until: datetime | None = None
    last_synced_at: datetime | None = None
    stale_after: datetime | None = None
    classification_version: int = BILLING_CONTRACT_VERSION
    customer_ref: str | None = None
    subscription_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "status": self.status,
            "plan_code": self.plan_code,
            "tier_code": self.tier_code,
            "tier_name": self.tier_name,
            "link_status": self.link_status,
            "current_period_end": self.current_period_end,
            "cancel_at_period_end": self.cancel_at_period_end,
            "trial_end": self.trial_end,
            "grace_period_until": self.grace_period_until,
            "last_synced_at": self.last_synced_at,
            "stale_after": self.stale_after,
            "classification_version": self.classification_version,
            "customer_ref": self.customer_ref,
            "subscription_ref": self.subscription_ref,
        }


@dataclass(frozen=True)
class SafePurchaseStatus:
    """Safe provider purchase fact; fulfillment remains consumer-owned."""

    provider: str = "stripe"
    purchase_ref: str | None = None
    status: str = PURCHASE_STATUS_PENDING
    credit_product_code: str | None = None
    quantity: int | None = None
    paid_at: datetime | None = None
    refunded_at: datetime | None = None
    disputed_at: datetime | None = None
    last_synced_at: datetime | None = None
    stale_after: datetime | None = None
    classification_version: int = BILLING_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "purchase_ref": self.purchase_ref,
            "status": self.status,
            "credit_product_code": self.credit_product_code,
            "quantity": self.quantity,
            "paid_at": self.paid_at,
            "refunded_at": self.refunded_at,
            "disputed_at": self.disputed_at,
            "last_synced_at": self.last_synced_at,
            "stale_after": self.stale_after,
            "classification_version": self.classification_version,
        }


def _normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _utc_now(now: datetime | str | None = None) -> datetime:
    parsed = _parse_datetime(now)
    if parsed is not None:
        return parsed
    current = datetime.now(timezone.utc)
    return current.replace(microsecond=0)


def _clean_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_int(value: Any, default: int) -> int:
    try:
        if isinstance(value, bool):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_subscription_status(value: Any, *, default: str = SUBSCRIPTION_STATUS_UNKNOWN) -> str:
    normalized = _normalize_text(value).replace("-", "_")
    normalized = _SUBSCRIPTION_ALIASES.get(normalized, normalized)
    if normalized in SUBSCRIPTION_STATUS_SET:
        return normalized
    return default if default in SUBSCRIPTION_STATUS_SET else SUBSCRIPTION_STATUS_UNKNOWN


def normalize_purchase_status(value: Any, *, default: str = PURCHASE_STATUS_UNKNOWN) -> str:
    normalized = _normalize_text(value).replace("-", "_")
    normalized = _PURCHASE_ALIASES.get(normalized, normalized)
    if normalized in PURCHASE_STATUS_SET:
        return normalized
    return default if default in PURCHASE_STATUS_SET else PURCHASE_STATUS_UNKNOWN


def normalize_link_status(value: Any, *, default: str = LINK_STATUS_NONE) -> str:
    normalized = _normalize_text(value).replace("-", "_")
    normalized = _LINK_ALIASES.get(normalized, normalized)
    if normalized in LINK_STATUS_SET:
        return normalized
    return default if default in LINK_STATUS_SET else LINK_STATUS_NONE


def is_terminal_subscription_status(status: Any) -> bool:
    return normalize_subscription_status(status) in TERMINAL_SUBSCRIPTION_STATUSES


def is_terminal_purchase_status(status: Any) -> bool:
    return normalize_purchase_status(status) in TERMINAL_PURCHASE_STATUSES


def is_current_provider_confirmed_subscription_status(status: Any) -> bool:
    return normalize_subscription_status(status) in CURRENT_PROVIDER_CONFIRMED_SUBSCRIPTION_STATUSES


def status_allows_current_paid_fact(
    status: Any,
    *,
    cancel_at_period_end: bool = False,
    current_period_end: datetime | str | None = None,
    now: datetime | str | None = None,
) -> bool:
    """Return whether the normalized provider fact is currently paid/trialing.

    This is not a product entitlement decision. It only says the provider fact is
    currently paid/trialing enough for a consumer to project with its own rules.
    """

    normalized = normalize_subscription_status(status)
    if normalized not in CURRENT_PROVIDER_CONFIRMED_SUBSCRIPTION_STATUSES:
        return False
    if not cancel_at_period_end:
        return True
    period_end = _parse_datetime(current_period_end)
    return bool(period_end and period_end > _utc_now(now))


def should_mark_stale(stale_after: datetime | str | None, *, now: datetime | str | None = None) -> bool:
    boundary = _parse_datetime(stale_after)
    return bool(boundary and _utc_now(now) >= boundary)


def stale_safe_status(status: Any) -> str:
    """Fail closed to stale/unknown without inventing product meaning."""

    normalized = normalize_subscription_status(status)
    if normalized in {SUBSCRIPTION_STATUS_FREE, SUBSCRIPTION_STATUS_FORMER, SUBSCRIPTION_STATUS_CANCELED}:
        return normalized
    if normalized == SUBSCRIPTION_STATUS_UNKNOWN:
        return SUBSCRIPTION_STATUS_UNKNOWN
    return SUBSCRIPTION_STATUS_STALE


def apply_subscription_freshness(
    status: Any,
    *,
    stale_after: datetime | str | None,
    now: datetime | str | None = None,
) -> str:
    normalized = normalize_subscription_status(status)
    if should_mark_stale(stale_after, now=now):
        return stale_safe_status(normalized)
    return normalized


def apply_purchase_freshness(
    status: Any,
    *,
    stale_after: datetime | str | None,
    now: datetime | str | None = None,
) -> str:
    normalized = normalize_purchase_status(status)
    if should_mark_stale(stale_after, now=now) and normalized in {PURCHASE_STATUS_PENDING, PURCHASE_STATUS_PAID}:
        return PURCHASE_STATUS_STALE
    return normalized


def terminal_no_paid_plan_code(status: Any, plan_code: Any = None) -> str:
    """Ensure terminal/free/unknown statuses do not advertise a current paid label."""

    normalized = normalize_subscription_status(status)
    if normalized in {
        SUBSCRIPTION_STATUS_FREE,
        SUBSCRIPTION_STATUS_CANCELED,
        SUBSCRIPTION_STATUS_FORMER,
        SUBSCRIPTION_STATUS_STALE,
        SUBSCRIPTION_STATUS_UNKNOWN,
        SUBSCRIPTION_STATUS_INCOMPLETE,
    }:
        return SUBSCRIPTION_STATUS_FREE
    return _clean_optional_text(plan_code) or SUBSCRIPTION_STATUS_FREE


def free_default_billing_status(
    *,
    provider: str = "stripe",
    classification_version: int = BILLING_CONTRACT_VERSION,
) -> SafeBillingStatus:
    """Return the project-scoped missing-row default.

    The default is provider-fact-only. It carries no provider history, product
    mapping, feature access, or account balance semantics.
    """

    return SafeBillingStatus(
        provider=_clean_optional_text(provider) or "stripe",
        status=SUBSCRIPTION_STATUS_FREE,
        plan_code=SUBSCRIPTION_STATUS_FREE,
        link_status=LINK_STATUS_NONE,
        classification_version=max(1, _coerce_int(classification_version, BILLING_CONTRACT_VERSION)),
    )


def free_default_billing_dict(**kwargs: Any) -> dict[str, Any]:
    return free_default_billing_status(**kwargs).to_dict()


def safe_status_from_row(
    row: Mapping[str, Any] | None,
    *,
    provider: str = "stripe",
    now: datetime | str | None = None,
) -> SafeBillingStatus:
    if not row:
        return free_default_billing_status(provider=provider)
    status = apply_subscription_freshness(
        row.get("status") or row.get("billing_status") or row.get("normalized_status"),
        stale_after=row.get("stale_after"),
        now=now,
    )
    safe_plan_code = terminal_no_paid_plan_code(status, row.get("plan_code"))
    exposes_current_plan = safe_plan_code != SUBSCRIPTION_STATUS_FREE
    return SafeBillingStatus(
        provider=_clean_optional_text(row.get("provider")) or provider,
        status=status,
        plan_code=safe_plan_code,
        tier_code=_clean_optional_text(row.get("tier_code")) if exposes_current_plan else None,
        tier_name=_clean_optional_text(row.get("tier_name")) if exposes_current_plan else None,
        link_status=normalize_link_status(row.get("link_status"), default=LINK_STATUS_LINKED if row else LINK_STATUS_NONE),
        current_period_end=_parse_datetime(row.get("current_period_end")),
        cancel_at_period_end=bool(row.get("cancel_at_period_end")),
        trial_end=_parse_datetime(row.get("trial_end")),
        grace_period_until=_parse_datetime(row.get("grace_period_until")),
        last_synced_at=_parse_datetime(row.get("last_synced_at")),
        stale_after=_parse_datetime(row.get("stale_after")),
        classification_version=max(1, _coerce_int(row.get("classification_version"), BILLING_CONTRACT_VERSION)),
        customer_ref=_clean_optional_text(row.get("customer_ref")),
        subscription_ref=_clean_optional_text(row.get("subscription_ref")),
    )


def safe_purchase_from_row(
    row: Mapping[str, Any] | None,
    *,
    provider: str = "stripe",
    now: datetime | str | None = None,
) -> SafePurchaseStatus | None:
    if not row:
        return None
    status = apply_purchase_freshness(row.get("status") or row.get("purchase_status"), stale_after=row.get("stale_after"), now=now)
    return SafePurchaseStatus(
        provider=_clean_optional_text(row.get("provider")) or provider,
        purchase_ref=_clean_optional_text(row.get("purchase_ref")),
        status=status,
        credit_product_code=_clean_optional_text(row.get("credit_product_code")),
        quantity=_coerce_int(row.get("quantity"), 0) or None,
        paid_at=_parse_datetime(row.get("paid_at")),
        refunded_at=_parse_datetime(row.get("refunded_at")),
        disputed_at=_parse_datetime(row.get("disputed_at")),
        last_synced_at=_parse_datetime(row.get("last_synced_at")),
        stale_after=_parse_datetime(row.get("stale_after")),
        classification_version=max(1, _coerce_int(row.get("classification_version"), BILLING_CONTRACT_VERSION)),
    )


def safe_status_from_provider_failure(current_snapshot: Mapping[str, Any] | None) -> SafeBillingStatus:
    """Preserve last safe fact as stale, or return unknown/free if absent."""

    if not current_snapshot:
        return SafeBillingStatus(status=SUBSCRIPTION_STATUS_UNKNOWN, plan_code=SUBSCRIPTION_STATUS_FREE)
    snapshot = safe_status_from_row(current_snapshot)
    stale_status = stale_safe_status(snapshot.status)
    payload = snapshot.to_dict()
    payload.update(
        {
            "status": stale_status,
            "plan_code": terminal_no_paid_plan_code(stale_status, snapshot.plan_code),
            "tier_code": None,
            "tier_name": None,
        }
    )
    return SafeBillingStatus(**payload)


__all__ = [
    "BILLING_CONTRACT_VERSION",
    "CURRENT_PROVIDER_CONFIRMED_SUBSCRIPTION_STATUSES",
    "LINK_STATUS_LINKED",
    "LINK_STATUS_NONE",
    "LINK_STATUS_PENDING",
    "LINK_STATUS_REVOKED",
    "LINK_STATUS_SET",
    "LINK_STATUS_STALE",
    "NORMALIZED_LINK_STATUSES",
    "NORMALIZED_PURCHASE_STATUSES",
    "NORMALIZED_SUBSCRIPTION_STATUSES",
    "PURCHASE_STATUS_DISPUTED",
    "PURCHASE_STATUS_DISPUTE_LOST",
    "PURCHASE_STATUS_DISPUTE_WON",
    "PURCHASE_STATUS_PAID",
    "PURCHASE_STATUS_PARTIALLY_REFUNDED",
    "PURCHASE_STATUS_PENDING",
    "PURCHASE_STATUS_REFUNDED",
    "PURCHASE_STATUS_SET",
    "PURCHASE_STATUS_STALE",
    "PURCHASE_STATUS_UNKNOWN",
    "SUBSCRIPTION_STATUS_ACTIVE",
    "SUBSCRIPTION_STATUS_CANCELED",
    "SUBSCRIPTION_STATUS_FORMER",
    "SUBSCRIPTION_STATUS_FREE",
    "SUBSCRIPTION_STATUS_INCOMPLETE",
    "SUBSCRIPTION_STATUS_PAST_DUE",
    "SUBSCRIPTION_STATUS_PAUSED",
    "SUBSCRIPTION_STATUS_PENDING",
    "SUBSCRIPTION_STATUS_SET",
    "SUBSCRIPTION_STATUS_STALE",
    "SUBSCRIPTION_STATUS_TRIALING",
    "SUBSCRIPTION_STATUS_UNKNOWN",
    "SUBSCRIPTION_STATUS_UNPAID",
    "SafeBillingStatus",
    "SafePurchaseStatus",
    "apply_purchase_freshness",
    "apply_subscription_freshness",
    "free_default_billing_dict",
    "free_default_billing_status",
    "is_current_provider_confirmed_subscription_status",
    "is_terminal_purchase_status",
    "is_terminal_subscription_status",
    "normalize_link_status",
    "normalize_purchase_status",
    "normalize_subscription_status",
    "safe_purchase_from_row",
    "safe_status_from_provider_failure",
    "safe_status_from_row",
    "should_mark_stale",
    "status_allows_current_paid_fact",
    "stale_safe_status",
    "terminal_no_paid_plan_code",
]
