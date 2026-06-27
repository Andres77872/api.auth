"""Resolve the subscription ``plan`` projection embedded in auth/session responses.

This helper deliberately lives outside the ``billing`` package and exposes a
provider-neutral name so that identity code paths (``auth.py``, ``auth_lifecycle.py``)
can import and call it without referencing provider/billing tokens — preserving the
billing-free authentication contract while still surfacing a subscription plan state.

Resolution is project -> billing group -> entitlement (subscriptions only). It is
fail-safe: any error or missing data yields ``state="none"`` rather than failing the
auth path.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Mapping

from src.Util.Models import SessionPlanStatus
from src.Util.billing.config import load_billing_config
from src.Util.db import db_billing


logger = logging.getLogger(__name__)

_ACTIVE_STATES = frozenset({"trial", "active"})


def _as_aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return None


def _derive_state(row: Mapping[str, Any]) -> tuple[str, bool]:
    """Collapse the internal entitlement status into the public 6-state contract."""

    if not int(row.get("has_billing_group") or 0):
        return "none", False

    status = str(row.get("status") or "").strip().lower()
    if status in ("", "free", "incomplete", "pending"):
        return "free", False
    if status == "trialing":
        return "trial", True
    if status == "active":
        return "active", True
    if status in ("past_due", "unpaid", "paused"):
        return "past_due", False
    if status in ("canceled", "former"):
        return "canceled", False
    if status in ("stale", "unknown"):
        period_end = _as_aware(row.get("current_period_end"))
        if period_end is not None and period_end > datetime.now(timezone.utc):
            return "active", True
        return "free", False
    return "free", False


def derive_session_plan(row: Mapping[str, Any] | None, *, billing_enabled: bool) -> SessionPlanStatus:
    """Map a ``sp_billing_get_session_plan`` row into a ``SessionPlanStatus``."""

    if not billing_enabled or not row:
        return SessionPlanStatus(state="none", active=False)

    state, active = _derive_state(row)
    if state in ("none", "free"):
        return SessionPlanStatus(
            provider=str(row.get("provider") or "stripe"),
            state=state,
            active=active,
        )
    return SessionPlanStatus(
        provider=str(row.get("provider") or "stripe"),
        state=state,
        active=active,
        plan_code=row.get("plan_code"),
        tier_code=row.get("tier_code"),
        current_period_end=row.get("current_period_end"),
        trial_end=row.get("trial_end"),
        cancel_at_period_end=bool(row.get("cancel_at_period_end") or False),
    )


def resolve_session_plan(user_id: str | None, project_id: str | None, *, provider: str = "stripe") -> SessionPlanStatus | None:
    """Resolve the session plan for a project-scoped consumer session.

    Returns ``None`` for sessions without a project (e.g. platform/root scope) so the
    caller can leave the response field unset. Never raises.
    """

    if not user_id or not project_id:
        return None

    try:
        config = load_billing_config()
        billing_enabled = bool(getattr(config, "billing_enabled", False))
    except Exception:
        billing_enabled = False

    if not billing_enabled:
        return SessionPlanStatus(state="none", active=False)

    try:
        row = db_billing.get_session_plan(user_id=user_id, project_id=project_id, provider=provider)
    except Exception:
        logger.debug("session plan lookup degraded to none for user/project scope")
        row = None

    return derive_session_plan(row, billing_enabled=billing_enabled)


__all__ = ["derive_session_plan", "resolve_session_plan"]
