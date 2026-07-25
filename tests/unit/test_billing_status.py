"""Focused unit contracts for provider-agnostic billing status helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest

from src.Util.billing import status as billing_status


UTC = timezone.utc
NOW = datetime(2026, 7, 24, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("cancelled", "canceled"),
        (" canceled-at-period-end ", "active"),
        ("PASTDUE", "past_due"),
        ("not-paid", "unpaid"),
        ("none", "free"),
    ],
)
def test_subscription_aliases_are_normalized(value: Any, expected: str) -> None:
    assert billing_status.normalize_subscription_status(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("complete", "paid"),
        ("completed", "paid"),
        ("succeeded", "paid"),
        ("partial-refund", "partially_refunded"),
        ("partially-refund", "partially_refunded"),
        ("chargeback", "disputed"),
        ("won", "dispute_won"),
        ("lost", "dispute_lost"),
    ],
)
def test_purchase_aliases_are_normalized(value: Any, expected: str) -> None:
    assert billing_status.normalize_purchase_status(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("unlinked", "none"),
        ("blocked", "revoked"),
        ("proof-required", "pending"),
    ],
)
def test_link_aliases_are_normalized(value: Any, expected: str) -> None:
    assert billing_status.normalize_link_status(value) == expected


@pytest.mark.parametrize(
    ("normalizer", "statuses"),
    [
        (
            billing_status.normalize_subscription_status,
            billing_status.NORMALIZED_SUBSCRIPTION_STATUSES,
        ),
        (
            billing_status.normalize_purchase_status,
            billing_status.NORMALIZED_PURCHASE_STATUSES,
        ),
        (
            billing_status.normalize_link_status,
            billing_status.NORMALIZED_LINK_STATUSES,
        ),
    ],
)
def test_every_canonical_status_is_accepted_case_insensitively(
    normalizer: Callable[..., str],
    statuses: tuple[str, ...],
) -> None:
    for status in statuses:
        assert normalizer(f" {status.upper()} ") == status


@pytest.mark.parametrize(
    ("normalizer", "valid_default", "hard_fallback"),
    [
        (
            billing_status.normalize_subscription_status,
            billing_status.SUBSCRIPTION_STATUS_FREE,
            billing_status.SUBSCRIPTION_STATUS_UNKNOWN,
        ),
        (
            billing_status.normalize_purchase_status,
            billing_status.PURCHASE_STATUS_PENDING,
            billing_status.PURCHASE_STATUS_UNKNOWN,
        ),
        (
            billing_status.normalize_link_status,
            billing_status.LINK_STATUS_PENDING,
            billing_status.LINK_STATUS_NONE,
        ),
    ],
)
@pytest.mark.parametrize(
    "malformed",
    [None, "", "   ", "not-a-status", True, 123, [], {}],
)
def test_malformed_status_values_use_only_safe_defaults(
    normalizer: Callable[..., str],
    valid_default: str,
    hard_fallback: str,
    malformed: Any,
) -> None:
    assert normalizer(malformed, default=valid_default) == valid_default
    assert normalizer(malformed, default="also-not-a-status") == hard_fallback


@pytest.mark.parametrize("status", billing_status.NORMALIZED_SUBSCRIPTION_STATUSES)
def test_subscription_terminal_and_current_state_sets_are_exact(status: str) -> None:
    assert billing_status.is_terminal_subscription_status(status) is (
        status in {"free", "canceled", "former"}
    )
    assert billing_status.is_current_provider_confirmed_subscription_status(status) is (
        status in {"trialing", "active"}
    )


@pytest.mark.parametrize("status", billing_status.NORMALIZED_PURCHASE_STATUSES)
def test_purchase_terminal_state_set_is_exact(status: str) -> None:
    assert billing_status.is_terminal_purchase_status(status) is (
        status in {"refunded", "dispute_won", "dispute_lost"}
    )


def test_state_predicates_normalize_aliases_and_reject_malformed_values() -> None:
    assert billing_status.is_terminal_subscription_status("cancelled") is True
    assert billing_status.is_current_provider_confirmed_subscription_status(
        "canceled-at-period-end"
    ) is True
    assert billing_status.is_terminal_purchase_status("won") is True

    assert billing_status.is_terminal_subscription_status({}) is False
    assert billing_status.is_current_provider_confirmed_subscription_status([]) is False
    assert billing_status.is_terminal_purchase_status(None) is False


@pytest.mark.parametrize("status", ["active", "trialing"])
def test_current_paid_fact_without_cancellation_does_not_require_period_end(
    status: str,
) -> None:
    assert billing_status.status_allows_current_paid_fact(
        status,
        cancel_at_period_end=False,
        current_period_end="malformed",
        now="malformed",
    )


@pytest.mark.parametrize(
    "status",
    [
        status
        for status in billing_status.NORMALIZED_SUBSCRIPTION_STATUSES
        if status not in {"active", "trialing"}
    ],
)
def test_non_current_subscription_never_allows_current_paid_fact(status: str) -> None:
    assert not billing_status.status_allows_current_paid_fact(
        status,
        cancel_at_period_end=True,
        current_period_end=NOW + timedelta(days=30),
        now=NOW,
    )


@pytest.mark.parametrize("status", ["active", "trialing", "canceled-at-period-end"])
@pytest.mark.parametrize(
    ("period_end", "expected"),
    [
        (NOW + timedelta(seconds=1), True),
        (NOW, False),
        (NOW - timedelta(seconds=1), False),
        (None, False),
        ("not-a-datetime", False),
    ],
)
def test_cancellation_is_current_only_before_a_valid_period_end(
    status: str,
    period_end: datetime | str | None,
    expected: bool,
) -> None:
    assert (
        billing_status.status_allows_current_paid_fact(
            status,
            cancel_at_period_end=True,
            current_period_end=period_end,
            now=NOW.isoformat().replace("+00:00", "Z"),
        )
        is expected
    )


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (NOW - timedelta(seconds=1), False),
        (NOW, True),
        (NOW + timedelta(seconds=1), True),
    ],
)
def test_staleness_changes_at_the_exact_boundary(
    now: datetime,
    expected: bool,
) -> None:
    assert billing_status.should_mark_stale(NOW, now=now) is expected


@pytest.mark.parametrize("boundary", [None, "", "not-a-datetime", 123, []])
def test_malformed_staleness_boundary_never_marks_a_fact_stale(
    boundary: Any,
) -> None:
    assert billing_status.should_mark_stale(boundary, now=NOW) is False


def test_malformed_now_value_falls_back_to_the_current_utc_second(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz: timezone | None = None) -> FixedDateTime:
            return cls(2026, 7, 24, 12, 0, 0, tzinfo=tz or UTC)

    monkeypatch.setattr(billing_status, "datetime", FixedDateTime)

    assert billing_status.should_mark_stale(
        "2026-07-24T12:00:00Z",
        now="not-a-datetime",
    )


def test_staleness_normalizes_naive_and_offset_datetimes_to_utc_seconds() -> None:
    boundary = "2026-07-24T07:00:00-05:00"

    assert billing_status.should_mark_stale(boundary, now="2026-07-24T11:59:59Z") is False
    assert billing_status.should_mark_stale(boundary, now=datetime(2026, 7, 24, 12)) is True


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("free", "free"),
        ("pending", "stale"),
        ("incomplete", "stale"),
        ("trialing", "stale"),
        ("active", "stale"),
        ("past_due", "stale"),
        ("unpaid", "stale"),
        ("paused", "stale"),
        ("canceled", "canceled"),
        ("former", "former"),
        ("stale", "stale"),
        ("unknown", "unknown"),
        ("cancelled", "canceled"),
        ("malformed", "unknown"),
    ],
)
def test_subscription_stale_fallback_preserves_only_safe_terminal_states(
    status: Any,
    expected: str,
) -> None:
    assert billing_status.stale_safe_status(status) == expected
    assert (
        billing_status.apply_subscription_freshness(
            status,
            stale_after=NOW,
            now=NOW,
        )
        == expected
    )


@pytest.mark.parametrize("status", billing_status.NORMALIZED_SUBSCRIPTION_STATUSES)
def test_fresh_subscription_fact_keeps_its_normalized_state(status: str) -> None:
    assert (
        billing_status.apply_subscription_freshness(
            status.upper(),
            stale_after=NOW,
            now=NOW - timedelta(seconds=1),
        )
        == status
    )


@pytest.mark.parametrize("status", billing_status.NORMALIZED_PURCHASE_STATUSES)
def test_only_pending_or_paid_purchase_facts_decay_to_stale(status: str) -> None:
    expected = "stale" if status in {"pending", "paid"} else status

    assert (
        billing_status.apply_purchase_freshness(
            status,
            stale_after=NOW,
            now=NOW,
        )
        == expected
    )


def test_fresh_purchase_alias_is_normalized_without_becoming_stale() -> None:
    assert (
        billing_status.apply_purchase_freshness(
            "succeeded",
            stale_after=NOW,
            now=NOW - timedelta(seconds=1),
        )
        == billing_status.PURCHASE_STATUS_PAID
    )


@pytest.mark.parametrize(
    "status",
    ["free", "canceled", "former", "stale", "unknown", "incomplete", "cancelled"],
)
def test_non_advertising_subscription_states_force_free_plan(status: str) -> None:
    assert (
        billing_status.terminal_no_paid_plan_code(status, " premium ")
        == billing_status.SUBSCRIPTION_STATUS_FREE
    )


@pytest.mark.parametrize("status", ["pending", "trialing", "active", "past_due", "unpaid", "paused"])
def test_plan_code_is_preserved_only_when_status_policy_allows_it(status: str) -> None:
    assert billing_status.terminal_no_paid_plan_code(status, " premium ") == "premium"
    assert (
        billing_status.terminal_no_paid_plan_code(status, "   ")
        == billing_status.SUBSCRIPTION_STATUS_FREE
    )


def test_free_default_is_project_safe_and_coerces_malformed_metadata() -> None:
    default = billing_status.free_default_billing_status(
        provider="   ",
        classification_version=True,
    )

    assert default.to_dict() == {
        "provider": "stripe",
        "status": "free",
        "plan_code": "free",
        "tier_code": None,
        "tier_name": None,
        "link_status": "none",
        "current_period_end": None,
        "cancel_at_period_end": False,
        "trial_end": None,
        "grace_period_until": None,
        "last_synced_at": None,
        "stale_after": None,
        "classification_version": billing_status.BILLING_CONTRACT_VERSION,
        "customer_ref": None,
        "subscription_ref": None,
    }
    assert billing_status.free_default_billing_dict(
        provider=" alternate ",
        classification_version="3",
    )["provider"] == "alternate"
    assert billing_status.free_default_billing_dict(classification_version="3")[
        "classification_version"
    ] == 3


@pytest.mark.parametrize(
    "row",
    [
        {"billing_status": "past-due"},
        {"normalized_status": "TRIALING"},
    ],
)
def test_safe_status_row_accepts_legacy_status_keys(row: dict[str, Any]) -> None:
    expected = "past_due" if "billing_status" in row else "trialing"

    assert billing_status.safe_status_from_row(row, now=NOW).status == expected


def test_safe_status_row_normalizes_fields_and_datetime_values() -> None:
    row = {
        "provider": " stripe ",
        "status": " ACTIVE ",
        "plan_code": " premium ",
        "tier_code": " pro ",
        "tier_name": " Pro ",
        "link_status": "proof-required",
        "current_period_end": "2026-08-24T07:00:00-05:00",
        "cancel_at_period_end": 1,
        "trial_end": datetime(2026, 7, 31, 12, 0, 0, 999999),
        "grace_period_until": "malformed",
        "last_synced_at": "2026-07-24T12:00:00.987654Z",
        "stale_after": "2026-07-25T12:00:00Z",
        "classification_version": "3",
        "customer_ref": " customer-local ",
        "subscription_ref": " subscription-local ",
    }

    snapshot = billing_status.safe_status_from_row(row, now=NOW)

    assert snapshot.to_dict() == {
        "provider": "stripe",
        "status": "active",
        "plan_code": "premium",
        "tier_code": "pro",
        "tier_name": "Pro",
        "link_status": "pending",
        "current_period_end": datetime(2026, 8, 24, 12, 0, 0, tzinfo=UTC),
        "cancel_at_period_end": True,
        "trial_end": datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC),
        "grace_period_until": None,
        "last_synced_at": NOW,
        "stale_after": datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC),
        "classification_version": 3,
        "customer_ref": "customer-local",
        "subscription_ref": "subscription-local",
    }


def test_safe_status_row_fails_closed_at_exact_staleness_boundary() -> None:
    snapshot = billing_status.safe_status_from_row(
        {
            "status": "active",
            "plan_code": "premium",
            "tier_code": "pro",
            "tier_name": "Pro",
            "stale_after": NOW,
        },
        now=NOW,
    )

    assert snapshot.status == "stale"
    assert snapshot.plan_code == "free"
    assert snapshot.tier_code is None
    assert snapshot.tier_name is None


def test_safe_status_row_handles_missing_and_malformed_values() -> None:
    assert billing_status.safe_status_from_row(None, provider="alternate") == (
        billing_status.free_default_billing_status(provider="alternate")
    )
    assert billing_status.safe_status_from_row({}, provider="alternate") == (
        billing_status.free_default_billing_status(provider="alternate")
    )

    snapshot = billing_status.safe_status_from_row(
        {
            "provider": " ",
            "status": ["active"],
            "plan_code": {"unexpected": "shape"},
            "tier_code": ["unexpected"],
            "tier_name": "ignored",
            "link_status": {"unexpected": "shape"},
            "current_period_end": 123,
            "cancel_at_period_end": 0,
            "trial_end": "not-a-date",
            "last_synced_at": [],
            "stale_after": {},
            "classification_version": True,
            "customer_ref": " ",
            "subscription_ref": None,
        },
        provider="fallback",
        now=NOW,
    )

    assert snapshot.provider == "fallback"
    assert snapshot.status == "unknown"
    assert snapshot.plan_code == "free"
    assert snapshot.tier_code is None
    assert snapshot.tier_name is None
    assert snapshot.link_status == "linked"
    assert snapshot.current_period_end is None
    assert snapshot.cancel_at_period_end is False
    assert snapshot.trial_end is None
    assert snapshot.last_synced_at is None
    assert snapshot.stale_after is None
    assert snapshot.classification_version == billing_status.BILLING_CONTRACT_VERSION
    assert snapshot.customer_ref is None
    assert snapshot.subscription_ref is None


def test_safe_purchase_row_normalizes_and_applies_exact_freshness_boundary() -> None:
    purchase = billing_status.safe_purchase_from_row(
        {
            "provider": " stripe ",
            "purchase_ref": " purchase-local ",
            "status": "succeeded",
            "credit_product_code": " credits-100 ",
            "quantity": "2",
            "paid_at": "2026-07-24T07:00:00-05:00",
            "refunded_at": "",
            "disputed_at": "malformed",
            "last_synced_at": datetime(2026, 7, 24, 12, 0, 0, 42),
            "stale_after": NOW,
            "classification_version": "4",
        },
        now=NOW,
    )

    assert purchase is not None
    assert purchase.to_dict() == {
        "provider": "stripe",
        "purchase_ref": "purchase-local",
        "status": "stale",
        "credit_product_code": "credits-100",
        "quantity": 2,
        "paid_at": NOW,
        "refunded_at": None,
        "disputed_at": None,
        "last_synced_at": NOW,
        "stale_after": NOW,
        "classification_version": 4,
    }


def test_safe_purchase_row_handles_missing_and_malformed_values() -> None:
    assert billing_status.safe_purchase_from_row(None, now=NOW) is None
    assert billing_status.safe_purchase_from_row({}, now=NOW) is None

    purchase = billing_status.safe_purchase_from_row(
        {
            "provider": " ",
            "purchase_status": {"unexpected": "shape"},
            "purchase_ref": " ",
            "credit_product_code": None,
            "quantity": True,
            "paid_at": 123,
            "refunded_at": [],
            "disputed_at": "not-a-date",
            "last_synced_at": {},
            "stale_after": None,
            "classification_version": False,
        },
        provider="fallback",
        now=NOW,
    )

    assert purchase is not None
    assert purchase.provider == "fallback"
    assert purchase.purchase_ref is None
    assert purchase.status == "unknown"
    assert purchase.credit_product_code is None
    assert purchase.quantity is None
    assert purchase.paid_at is None
    assert purchase.refunded_at is None
    assert purchase.disputed_at is None
    assert purchase.last_synced_at is None
    assert purchase.stale_after is None
    assert purchase.classification_version == billing_status.BILLING_CONTRACT_VERSION


@pytest.mark.parametrize(
    ("snapshot", "expected_status"),
    [
        (None, "unknown"),
        ({}, "unknown"),
        ({"status": "canceled", "plan_code": "premium"}, "canceled"),
        ({"status": "malformed", "plan_code": "premium"}, "unknown"),
    ],
)
def test_provider_failure_without_a_current_paid_fact_fails_closed(
    snapshot: dict[str, Any] | None,
    expected_status: str,
) -> None:
    fallback = billing_status.safe_status_from_provider_failure(snapshot)

    assert fallback.status == expected_status
    assert fallback.plan_code == "free"
    assert fallback.tier_code is None
    assert fallback.tier_name is None


def test_provider_failure_decays_active_fact_and_removes_paid_tier_metadata() -> None:
    fallback = billing_status.safe_status_from_provider_failure(
        {
            "provider": "stripe",
            "status": "active",
            "plan_code": "premium",
            "tier_code": "pro",
            "tier_name": "Pro",
            "link_status": "linked",
            "customer_ref": "customer-local",
            "subscription_ref": "subscription-local",
        }
    )

    assert fallback.status == "stale"
    assert fallback.plan_code == "free"
    assert fallback.tier_code is None
    assert fallback.tier_name is None
    assert fallback.link_status == "linked"
    assert fallback.customer_ref == "customer-local"
    assert fallback.subscription_ref == "subscription-local"
