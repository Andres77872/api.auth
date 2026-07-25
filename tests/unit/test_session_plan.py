"""Unit contracts for the provider-neutral session plan projection."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from src.Util import session_plan


PAST = datetime(2000, 1, 1, tzinfo=timezone.utc)
FUTURE = datetime(2100, 1, 1, tzinfo=timezone.utc)
NAIVE_FUTURE = datetime(2100, 1, 1)


def _assert_plan(
    plan,
    *,
    provider: str = "stripe",
    state: str,
    active: bool,
    plan_code=None,
    tier_code=None,
    current_period_end=None,
    trial_end=None,
    cancel_at_period_end: bool = False,
) -> None:
    assert plan.provider == provider
    assert plan.state == state
    assert plan.active is active
    assert plan.plan_code == plan_code
    assert plan.tier_code == tier_code
    assert plan.current_period_end == current_period_end
    assert plan.trial_end == trial_end
    assert plan.cancel_at_period_end is cancel_at_period_end


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(FUTURE, FUTURE, id="aware-datetime-is-preserved"),
        pytest.param(
            NAIVE_FUTURE,
            NAIVE_FUTURE.replace(tzinfo=timezone.utc),
            id="naive-datetime-is-assumed-utc",
        ),
        pytest.param(None, None, id="none"),
        pytest.param("2100-01-01T00:00:00Z", None, id="timestamp-string"),
        pytest.param(1_234_567_890, None, id="unix-timestamp"),
    ],
)
def test_as_aware_accepts_only_datetimes_and_normalizes_naive_values(value, expected):
    result = session_plan._as_aware(value)

    assert result == expected
    if value is FUTURE:
        assert result is value


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        pytest.param({"status": "active"}, ("none", False), id="missing-billing-group"),
        pytest.param(
            {"has_billing_group": 0, "status": "active"},
            ("none", False),
            id="no-billing-group",
        ),
        pytest.param(
            {"has_billing_group": 1},
            ("free", False),
            id="missing-status",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "  "},
            ("free", False),
            id="blank-status",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": " FREE "},
            ("free", False),
            id="free-normalized",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "incomplete"},
            ("free", False),
            id="incomplete",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "pending"},
            ("free", False),
            id="pending",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": " TRIALING "},
            ("trial", True),
            id="trialing-normalized",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "ACTIVE"},
            ("active", True),
            id="active-normalized",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "past_due"},
            ("past_due", False),
            id="past-due",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "unpaid"},
            ("past_due", False),
            id="unpaid",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "paused"},
            ("past_due", False),
            id="paused",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "canceled"},
            ("canceled", False),
            id="canceled",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "former"},
            ("canceled", False),
            id="former",
        ),
        pytest.param(
            {
                "has_billing_group": 1,
                "status": "stale",
                "current_period_end": FUTURE,
            },
            ("active", True),
            id="stale-with-future-aware-period",
        ),
        pytest.param(
            {
                "has_billing_group": 1,
                "status": "unknown",
                "current_period_end": NAIVE_FUTURE,
            },
            ("active", True),
            id="unknown-with-future-naive-period",
        ),
        pytest.param(
            {
                "has_billing_group": 1,
                "status": "stale",
                "current_period_end": PAST,
            },
            ("free", False),
            id="stale-with-expired-period",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "unknown"},
            ("free", False),
            id="unknown-without-period",
        ),
        pytest.param(
            {
                "has_billing_group": 1,
                "status": "unknown",
                "current_period_end": "2100-01-01T00:00:00Z",
            },
            ("free", False),
            id="unknown-with-non-datetime-period",
        ),
        pytest.param(
            {"has_billing_group": 1, "status": "provider_specific"},
            ("free", False),
            id="unsupported-status",
        ),
    ],
)
def test_derive_state_collapses_internal_statuses_to_the_public_contract(row, expected):
    assert session_plan._derive_state(row) == expected


@pytest.mark.parametrize("status", ["stale", "unknown"])
def test_derive_state_does_not_treat_the_current_instant_as_active(status):
    row = {
        "has_billing_group": 1,
        "status": status,
        "current_period_end": datetime.now(timezone.utc),
    }

    assert session_plan._derive_state(row) == ("free", False)


@pytest.mark.parametrize(
    ("row", "billing_enabled"),
    [
        pytest.param(
            {"has_billing_group": 1, "status": "active"},
            False,
            id="billing-disabled",
        ),
        pytest.param(None, True, id="missing-row"),
        pytest.param({}, True, id="empty-row"),
    ],
)
def test_derive_session_plan_returns_an_empty_projection_when_resolution_is_unavailable(
    row,
    billing_enabled,
):
    plan = session_plan.derive_session_plan(row, billing_enabled=billing_enabled)

    _assert_plan(plan, state="none", active=False)


@pytest.mark.parametrize(
    ("row_overrides", "expected_state", "expected_active", "include_details"),
    [
        pytest.param(
            {"has_billing_group": 0, "status": "active"},
            "none",
            False,
            False,
            id="no-group-suppresses-paid-fields",
        ),
        pytest.param(
            {"status": "free"},
            "free",
            False,
            False,
            id="free-suppresses-paid-fields",
        ),
        pytest.param(
            {"status": "trialing"},
            "trial",
            True,
            True,
            id="trial",
        ),
        pytest.param(
            {"status": "active"},
            "active",
            True,
            True,
            id="active",
        ),
        pytest.param(
            {"status": "past_due"},
            "past_due",
            False,
            True,
            id="past-due",
        ),
        pytest.param(
            {"status": "canceled"},
            "canceled",
            False,
            True,
            id="canceled",
        ),
        pytest.param(
            {"status": "stale", "current_period_end": FUTURE},
            "active",
            True,
            True,
            id="stale-with-unexpired-period",
        ),
        pytest.param(
            {"status": "unknown", "current_period_end": PAST},
            "free",
            False,
            False,
            id="unknown-with-expired-period-suppresses-paid-fields",
        ),
    ],
)
def test_derive_session_plan_projects_and_suppresses_fields_by_public_state(
    row_overrides,
    expected_state,
    expected_active,
    include_details,
):
    trial_end = datetime(2099, 12, 1, tzinfo=timezone.utc)
    row = {
        "has_billing_group": 1,
        "provider": "patreon",
        "status": "active",
        "plan_code": "magic_worlds_pro",
        "tier_code": "architect",
        "current_period_end": FUTURE,
        "trial_end": trial_end,
        "cancel_at_period_end": 1,
        **row_overrides,
    }

    plan = session_plan.derive_session_plan(row, billing_enabled=True)

    details = (
        {
            "plan_code": "magic_worlds_pro",
            "tier_code": "architect",
            "current_period_end": row["current_period_end"],
            "trial_end": trial_end,
            "cancel_at_period_end": True,
        }
        if include_details
        else {}
    )
    _assert_plan(
        plan,
        provider="patreon",
        state=expected_state,
        active=expected_active,
        **details,
    )


@pytest.mark.parametrize(
    ("provider", "expected"),
    [
        pytest.param(None, "stripe", id="missing"),
        pytest.param("", "stripe", id="blank"),
        pytest.param("stripe", "stripe", id="stripe"),
        pytest.param("patreon", "patreon", id="patreon"),
    ],
)
def test_derive_session_plan_normalizes_the_provider_default(provider, expected):
    plan = session_plan.derive_session_plan(
        {
            "has_billing_group": 1,
            "status": "active",
            "provider": provider,
        },
        billing_enabled=True,
    )

    _assert_plan(plan, provider=expected, state="active", active=True)


@pytest.mark.parametrize(
    ("user_id", "project_id"),
    [
        pytest.param(None, "project-1", id="missing-user"),
        pytest.param("", "project-1", id="blank-user"),
        pytest.param("user-1", None, id="missing-project"),
        pytest.param("user-1", "", id="blank-project"),
        pytest.param(None, None, id="missing-scope"),
    ],
)
def test_resolve_session_plan_skips_unscoped_sessions(
    monkeypatch,
    user_id,
    project_id,
):
    load_config = Mock()
    lookup = Mock()
    monkeypatch.setattr(session_plan, "load_billing_config", load_config)
    monkeypatch.setattr(session_plan.db_billing, "get_session_plan", lookup)

    assert session_plan.resolve_session_plan(user_id, project_id) is None
    load_config.assert_not_called()
    lookup.assert_not_called()


@pytest.mark.parametrize(
    "config_behavior",
    [
        pytest.param("disabled", id="billing-disabled"),
        pytest.param("missing-flag", id="config-without-billing-flag"),
        pytest.param("error", id="config-load-error"),
    ],
)
def test_resolve_session_plan_degrades_before_lookup_when_billing_is_unavailable(
    monkeypatch,
    config_behavior,
):
    if config_behavior == "disabled":
        load_config = Mock(return_value=SimpleNamespace(billing_enabled=False))
    elif config_behavior == "missing-flag":
        load_config = Mock(return_value=SimpleNamespace())
    else:
        load_config = Mock(side_effect=RuntimeError("synthetic config failure"))
    lookup = Mock()
    monkeypatch.setattr(session_plan, "load_billing_config", load_config)
    monkeypatch.setattr(session_plan.db_billing, "get_session_plan", lookup)

    plan = session_plan.resolve_session_plan("user-1", "project-1")

    _assert_plan(plan, state="none", active=False)
    load_config.assert_called_once_with()
    lookup.assert_not_called()


@pytest.mark.parametrize(
    ("provider", "status", "expected_state", "expected_active"),
    [
        pytest.param("stripe", "trialing", "trial", True, id="stripe-trial"),
        pytest.param("patreon", "active", "active", True, id="patreon-active"),
        pytest.param("stripe", "unpaid", "past_due", False, id="stripe-unpaid"),
    ],
)
def test_resolve_session_plan_looks_up_the_exact_scope_and_provider(
    monkeypatch,
    provider,
    status,
    expected_state,
    expected_active,
):
    load_config = Mock(return_value=SimpleNamespace(billing_enabled=True))
    lookup = Mock(
        return_value={
            "has_billing_group": 1,
            "provider": provider,
            "status": status,
            "plan_code": "magic_worlds_pro",
            "tier_code": "architect",
            "current_period_end": FUTURE,
        }
    )
    monkeypatch.setattr(session_plan, "load_billing_config", load_config)
    monkeypatch.setattr(session_plan.db_billing, "get_session_plan", lookup)

    plan = session_plan.resolve_session_plan(
        "user-1",
        "project-1",
        provider=provider,
    )

    _assert_plan(
        plan,
        provider=provider,
        state=expected_state,
        active=expected_active,
        plan_code="magic_worlds_pro",
        tier_code="architect",
        current_period_end=FUTURE,
    )
    load_config.assert_called_once_with()
    lookup.assert_called_once_with(
        user_id="user-1",
        project_id="project-1",
        provider=provider,
    )


@pytest.mark.parametrize(
    "lookup_behavior",
    [
        pytest.param("missing-row", id="missing-row"),
        pytest.param("error", id="lookup-error"),
    ],
)
def test_resolve_session_plan_degrades_lookup_failures_without_leaking_scope(
    monkeypatch,
    caplog,
    lookup_behavior,
):
    load_config = Mock(return_value=SimpleNamespace(billing_enabled=True))
    if lookup_behavior == "missing-row":
        lookup = Mock(return_value=None)
    else:
        lookup = Mock(side_effect=RuntimeError("synthetic lookup failure"))
    monkeypatch.setattr(session_plan, "load_billing_config", load_config)
    monkeypatch.setattr(session_plan.db_billing, "get_session_plan", lookup)

    with caplog.at_level(logging.DEBUG, logger=session_plan.__name__):
        plan = session_plan.resolve_session_plan(
            "sensitive-user-id",
            "sensitive-project-id",
            provider="patreon",
        )

    _assert_plan(plan, state="none", active=False)
    lookup.assert_called_once_with(
        user_id="sensitive-user-id",
        project_id="sensitive-project-id",
        provider="patreon",
    )
    log_text = caplog.text
    assert "sensitive-user-id" not in log_text
    assert "sensitive-project-id" not in log_text
    if lookup_behavior == "error":
        assert "session plan lookup degraded to none" in log_text
    else:
        assert log_text == ""
