"""ROOT-only admin API for Patreon operational status.

The endpoint in this module is intentionally read-only. Patreon remains an
entitlement/link integration only; this route never returns provider secrets,
raw provider identifiers, raw payloads, hashes, fingerprints, or login/session
material.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Mapping, Optional

from fastapi import APIRouter, Body, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util import auth_constants as constants
from src.Util.Models import (
    PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES,
    PaginationInfo,
    PatreonAdminEntitlementItem,
    PatreonAdminEntitlementsListResponse,
    PatreonAdminResyncRequest,
    PatreonAdminSyncJobItem,
    PatreonAdminSyncJobsListResponse,
    PatreonAdminTierMapItem,
    PatreonAdminTierMapListResponse,
    PatreonAdminWebhookItem,
    PatreonAdminWebhookListResponse,
    PatreonResyncAcceptedResponse,
    assert_patreon_response_model_allow_lists,
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityType
from src.Util.db import db_patreon, get_user_by_hash, is_root_user
from src.Util.decorators import log_and_handle_errors
from src.Util.error_handler import (
    AuthorizationError,
    ErrorCode,
    NotFoundError,
    RateLimitError,
    ValidationError,
)
from src.Util.log_context_models import LogContext
from src.Util.patreon import sync as patreon_sync
from src.Util.patreon.config import load_patreon_config
from src.Util.patreon.rate_limit import PatreonRateLimiter, PatreonRateLimitExceeded
from src.Util.system_metrics import SystemMetrics


router = APIRouter(prefix="/admin/patreon", tags=["Admin - Patreon"])
security = HTTPBearerOrCookie()

_REDACTED = "[REDACTED]"
_SAFE_FOR_ADMIN_EXACT_KEYS = frozenset(
    {
        # Operational timestamps/counters, not token material.
        "expires_at",
        "refreshed_at",
        "rotated_at",
        "raw_payload_capture",
        "raw_payload_retention_days",
        "raw_payloads",
    }
)
_FORBIDDEN_ADMIN_KEYS = frozenset(
    key.lower().replace("-", "_")
    for key in PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES
    if key.lower().replace("-", "_") not in _SAFE_FOR_ADMIN_EXACT_KEYS
)
_SECRET_ENV_NAME_FRAGMENTS = (
    "TOKEN",
    "SECRET",
    "PEPPER",
    "BEARER",
    "ENCRYPTION_KEY",
)


def _require_root(log_context: LogContext) -> None:
    if log_context is None or not is_root_user(log_context.user_id):
        raise AuthorizationError(
            message="ROOT access required to inspect Patreon status",
            error_code=ErrorCode.ACCESS_DENIED,
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _secret_env_values() -> tuple[str, ...]:
    values: list[str] = []
    for name, value in os.environ.items():
        if not name.startswith("PATREON_"):
            continue
        if not any(fragment in name for fragment in _SECRET_ENV_NAME_FRAGMENTS):
            continue
        candidate = str(value or "").strip()
        if len(candidate) >= 8 and candidate.lower() not in {"false", "true", "disabled"}:
            values.append(candidate)
    return tuple(values)


def _redact_secret_values(text: str) -> str:
    redacted = text
    for secret_value in _secret_env_values():
        redacted = redacted.replace(secret_value, _REDACTED)
    return redacted


def _sanitize_patreon_admin_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            key_text = str(key)
            normalized_key = key_text.lower().replace("-", "_")
            if normalized_key in _FORBIDDEN_ADMIN_KEYS or normalized_key == "error":
                sanitized[key_text] = _REDACTED
                continue
            sanitized[key_text] = _sanitize_patreon_admin_value(child)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_patreon_admin_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_patreon_admin_value(item) for item in value]
    if isinstance(value, str):
        return _redact_secret_values(value)
    return value


# Test seam: defaults to a real Redis-backed limiter without side effects at import.
rate_limiter: PatreonRateLimiter | None = None


def _current_rate_limiter() -> PatreonRateLimiter:
    return rate_limiter or PatreonRateLimiter()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _pagination(limit: int, offset: int, total: int) -> PaginationInfo:
    return PaginationInfo(
        limit=limit,
        offset=offset,
        total=total,
        has_more=(offset + limit) < total,
    )


def _admin_list_response(model: Any) -> Dict[str, Any]:
    """Serialize an admin list DTO through its allow-list, then redact defensively."""

    return _sanitize_patreon_admin_value(model.model_dump_safe(mode="json"))


@router.get("/status")
@log_and_handle_errors(
    operation_name="get_admin_patreon_status",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def get_admin_patreon_status(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return non-secret Patreon operational status for the ROOT dashboard."""

    _require_root(log_context)
    metrics = _sanitize_patreon_admin_value(SystemMetrics.get_patreon_metrics())
    if not isinstance(metrics, dict):
        metrics = {"status": "unknown"}
    return {
        "success": True,
        "status": str(metrics.get("status") or "unknown"),
        "generated_at": _now_iso(),
        **metrics,
    }


@router.get("/entitlements")
@log_and_handle_errors(
    operation_name="list_admin_patreon_entitlements",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_admin_patreon_entitlements(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, max_length=32),
    plan_code: Optional[str] = Query(None, max_length=64),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return a paginated, sanitized list of current Patreon entitlements (ROOT)."""

    _require_root(log_context)
    rows, total = db_patreon.list_patreon_entitlements_admin(
        status=status,
        plan_code=plan_code,
        limit=limit,
        offset=offset,
    )
    items = [
        PatreonAdminEntitlementItem(
            user_hash=str(row.get("user_hash") or ""),
            display_name=row.get("display_name"),
            status=str(row.get("entitlement_status") or "free"),
            link_status=str(row.get("link_status") or "none"),
            plan_code=str(row.get("plan_code") or "free"),
            tier_code=row.get("tier_code"),
            tier_name=row.get("tier_name"),
            last_synced_at=row.get("last_synced_at"),
            updated_at=row.get("updated_at"),
        )
        for row in rows
    ]
    return _admin_list_response(
        PatreonAdminEntitlementsListResponse(items=items, pagination=_pagination(limit, offset, total))
    )


@router.get("/entitlements/{user_hash}")
@log_and_handle_errors(
    operation_name="get_admin_patreon_entitlement",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def get_admin_patreon_entitlement(
    user_hash: str,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return a single user's normalized Patreon entitlement detail (ROOT)."""

    _require_root(log_context)
    safe_hash = str(user_hash or "").strip()
    if not safe_hash:
        raise ValidationError(message="user_hash is required", error_code=ErrorCode.INVALID_INPUT)
    row = db_patreon.get_entitlement_by_user_hash(safe_hash)
    if not row:
        raise NotFoundError(message="Patreon entitlement not found")
    response = patreon_sync.db_entitlement_row_to_s2s_response(row, user_hash=safe_hash, now=_utc_now())
    return _sanitize_patreon_admin_value(response.model_dump_safe(mode="json"))


@router.get("/tier-map")
@log_and_handle_errors(
    operation_name="list_admin_patreon_tier_map",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_admin_patreon_tier_map(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    active: Optional[bool] = Query(None),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return the configured tier-map entries (fingerprints + codes only, ROOT)."""

    _require_root(log_context)
    rows, total = db_patreon.list_patreon_tier_map_admin(active=active, limit=limit, offset=offset)
    items = [
        PatreonAdminTierMapItem(
            campaign_fingerprint=row.get("campaign_fingerprint"),
            campaign_name=row.get("campaign_name"),
            tier_fingerprint=row.get("tier_fingerprint"),
            plan_code=str(row.get("plan_code") or ""),
            tier_code=str(row.get("tier_code") or ""),
            tier_name=row.get("tier_name"),
            priority=int(row.get("priority") or 0),
            active=bool(row.get("active")),
            effective_from=row.get("effective_from"),
            effective_until=row.get("effective_until"),
        )
        for row in rows
    ]
    return _admin_list_response(
        PatreonAdminTierMapListResponse(items=items, pagination=_pagination(limit, offset, total))
    )


@router.get("/sync-jobs")
@log_and_handle_errors(
    operation_name="list_admin_patreon_sync_jobs",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_admin_patreon_sync_jobs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, max_length=32),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return a paginated list of sync jobs (errors reduced to a flag, ROOT)."""

    _require_root(log_context)
    rows, total = db_patreon.list_patreon_sync_jobs_admin(status=status, limit=limit, offset=offset)
    items = [
        PatreonAdminSyncJobItem(
            job_id=str(row.get("job_id") or ""),
            job_type=str(row.get("job_type") or ""),
            status=str(row.get("status") or ""),
            priority=int(row.get("priority") or 0),
            attempts=int(row.get("attempts") or 0),
            max_attempts=int(row.get("max_attempts") or 0),
            not_before=row.get("not_before"),
            source=row.get("source"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
            completed_at=row.get("completed_at"),
            has_error=bool(row.get("has_error")),
        )
        for row in rows
    ]
    return _admin_list_response(
        PatreonAdminSyncJobsListResponse(items=items, pagination=_pagination(limit, offset, total))
    )


@router.get("/webhooks")
@log_and_handle_errors(
    operation_name="list_admin_patreon_webhooks",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_admin_patreon_webhooks(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    status: Optional[str] = Query(None, max_length=32),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return a paginated list of webhook deliveries (no raw payloads, ROOT)."""

    _require_root(log_context)
    rows, total = db_patreon.list_patreon_webhooks_admin(status=status, limit=limit, offset=offset)
    items = [
        PatreonAdminWebhookItem(
            delivery_id=str(row.get("delivery_id") or ""),
            event_type=str(row.get("event_type") or ""),
            status=str(row.get("status") or ""),
            signature_valid=bool(row.get("signature_valid")),
            received_at=row.get("received_at"),
            processed_at=row.get("processed_at"),
        )
        for row in rows
    ]
    return _admin_list_response(
        PatreonAdminWebhookListResponse(items=items, pagination=_pagination(limit, offset, total))
    )


@router.post("/resync")
@log_and_handle_errors(
    operation_name="enqueue_admin_patreon_resync",
    activity_type=ActivityType.PATREON_SYNC_STARTED,
    log_success=True,
)
async def enqueue_admin_patreon_resync(
    scope: Literal["user", "all"] = Body("user"),
    user_hash: Optional[str] = Body(None),
    reason: Optional[str] = Body(None),
    force: bool = Body(False),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Enqueue an admin-triggered Patreon resync (scope=user or scope=all, ROOT).

    Reuses the same enqueue path as the worker/S2S surface. scope='user' enqueues a
    per-user member resync; scope='all' enqueues a single full-campaign job (no
    campaign id) which the worker drains as a full sweep over every configured
    campaign. The job is only processed if the Patreon sync worker is running.
    """

    _require_root(log_context)
    payload = PatreonAdminResyncRequest(scope=scope, user_hash=user_hash, reason=reason, force=force)
    config = load_patreon_config()
    if not bool(getattr(config, "sync_enabled", False)):
        return {
            "success": True,
            "accepted": False,
            "status": "disabled",
            "message": "Patreon sync is disabled.",
        }

    try:
        _current_rate_limiter().check_sync_enqueue(
            kind=patreon_sync.JOB_TYPE_USER_MEMBER,
            user_id=(payload.user_hash or "admin"),
            source="manual",
        )
    except PatreonRateLimitExceeded as exc:
        retry_after = max(1, int(getattr(exc, "retry_after", 0) or 1))
        raise RateLimitError(
            message="Patreon resync rate limit exceeded.",
            retry_after_seconds=retry_after,
        )
    except Exception:
        # Fail-open on limiter backend errors: this is a ROOT-only endpoint.
        pass

    reason = payload.reason or "admin_dashboard_resync"
    job_id = f"psj-{uuid.uuid4().hex}"

    if payload.scope == "user":
        safe_hash = str(payload.user_hash or "").strip()
        if not safe_hash:
            raise ValidationError(
                message="user_hash is required for scope='user'",
                error_code=ErrorCode.INVALID_INPUT,
            )
        user = get_user_by_hash(safe_hash)
        if not user:
            raise NotFoundError(message="User not found")
        accepted = patreon_sync.enqueue_member_resync(
            user_id=user.id,
            user_hash=safe_hash,
            job_type=patreon_sync.JOB_TYPE_USER_MEMBER,
            job_id=job_id,
            priority=1 if payload.force else 5,
            source=constants.PATREON_SYNC_SOURCE_MANUAL_RESYNC,
            sanitized_metadata={"reason": reason, "source": "admin_dashboard"},
        )
        return _sanitize_patreon_admin_value(accepted.model_dump_safe(mode="json"))

    # scope == "all": one full-campaign job with no campaign id -> full sweep.
    db_patreon.enqueue_patreon_sync_job(
        job_id=job_id,
        job_type=patreon_sync.JOB_TYPE_FULL_CAMPAIGN,
        campaign_id=None,
        member_id_hash=None,
        user_id=None,
        dedupe_key_hash=patreon_sync.sync_job_dedupe_hash(patreon_sync.JOB_TYPE_FULL_CAMPAIGN, "all"),
        priority=1 if payload.force else 5,
        not_before=None,
        source="manual",
        sanitized_metadata={"reason": reason, "source": "admin_dashboard", "scope": "all"},
    )
    response = PatreonResyncAcceptedResponse(
        accepted=True,
        status="queued",
        correlation_id=job_id,
        message="Full Patreon resync enqueued.",
    )
    return _sanitize_patreon_admin_value(response.model_dump_safe(mode="json"))


def _assert_admin_route_hardening() -> None:
    """Fail fast if the admin Patreon DTOs drift outside their safe allow-lists."""

    assert_patreon_response_model_allow_lists()


_assert_admin_route_hardening()
