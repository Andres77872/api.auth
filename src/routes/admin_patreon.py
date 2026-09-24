"""ROOT-only admin API for Patreon operations.

Read-only status, entitlement, tier-map, sync-job and webhook-delivery views plus
one write (``POST /admin/patreon/resync``, which only queues sync jobs). Patreon
remains an entitlement/link integration only; these routes never return provider
secrets, raw provider identifiers, raw payloads, hashes (tier-map rows carry
non-reversible fingerprints only), or login/session material.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Literal, Mapping, Optional

from fastapi import APIRouter, Body, Depends, Path, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util import auth_constants as constants
from src.Util.Models import (
    PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES,
    PaginationInfo,
    PatreonAdminEntitlementItem,
    PatreonAdminEntitlementsListResponse,
    PatreonAdminHistoryItem,
    PatreonAdminHistoryResponse,
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
from src.Util.patreon.catalog import ensure_patreon_catalog_safely
from src.Util.patreon.config import PatreonConfigError, load_patreon_config
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


# OpenAPI notes shared by every route below (descriptions only).
_ROOT_ONLY_403 = {403: {"description": "The caller is not a root user."}}
_LIMIT_DESCRIPTION = "Page size (1-500)."
_OFFSET_DESCRIPTION = "Number of rows to skip."
_USER_HASH_PATH = Path(
    max_length=255,
    description="Public hash of the local user (not a Patreon identifier).",
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


@router.get("/status", responses=_ROOT_ONLY_403)
@log_and_handle_errors(
    operation_name="get_admin_patreon_status",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def get_admin_patreon_status(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return the Patreon integration's operational health for the root dashboard, with secrets redacted.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Responses:** `200` with overall `status` (`healthy`, `degraded`, `disabled` or `unknown`),
    `generated_at`, and component groups `readiness`, `creator_token`, `webhooks`, `snapshots`,
    `tier_map`, `proof_delivery`, `s2s`, `worker` (sync-worker heartbeat) and `sync_queue`, plus
    flat `metrics`. Provider secrets, raw Patreon identifiers, payloads and error text are never
    included. `403` for non-root callers.
    """

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


@router.get("/entitlements", responses=_ROOT_ONLY_403)
@log_and_handle_errors(
    operation_name="list_admin_patreon_entitlements",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_admin_patreon_entitlements(
    limit: int = Query(50, ge=1, le=500, description=_LIMIT_DESCRIPTION),
    offset: int = Query(0, ge=0, description=_OFFSET_DESCRIPTION),
    status: Optional[str] = Query(
        None,
        max_length=32,
        description="Exact entitlement status: `active`, `free`, `pending`, `former`, `revoked` or `stale`.",
    ),
    plan_code: Optional[str] = Query(None, max_length=64, description="Exact internal plan code, e.g. `free`."),
    link_status: Optional[str] = Query(
        None,
        max_length=32,
        description="Exact link status: `none`, `pending`, `linked`, `unlinked`, `revoked` or `stale`.",
    ),
    search: Optional[str] = Query(
        None,
        max_length=255,
        description="Exact `user_hash`, or a username/email prefix.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """List users' current Patreon entitlement snapshots, paginated and sanitized.

    Only users that have a stored entitlement snapshot are listed.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Responses:** `200` with `items[]` (`user_hash`, `display_name`, entitlement `status`,
    `link_status`, `plan_code`, `tier_code`, `tier_name`, `next_renewal_at`, `last_synced_at`,
    `stale_after`, `updated_at`) and `pagination`. No raw Patreon identifiers, emails or
    payloads. `403` for non-root callers.
    """

    _require_root(log_context)
    rows, total = db_patreon.list_patreon_entitlements_admin(
        status=status,
        plan_code=plan_code,
        link_status=link_status if isinstance(link_status, str) else None,
        search=search.strip() or None if isinstance(search, str) else None,
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
            next_renewal_at=row.get("next_renewal_at"),
            last_synced_at=row.get("last_synced_at"),
            stale_after=row.get("stale_after"),
            updated_at=row.get("updated_at"),
        )
        for row in rows
    ]
    return _admin_list_response(
        PatreonAdminEntitlementsListResponse(items=items, pagination=_pagination(limit, offset, total))
    )


@router.get(
    "/entitlements/{user_hash}",
    responses={**_ROOT_ONLY_403, 404: {"description": "No active user has this `user_hash`."}},
)
@log_and_handle_errors(
    operation_name="get_admin_patreon_entitlement",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def get_admin_patreon_entitlement(
    user_hash: Annotated[str, _USER_HASH_PATH],
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return one user's normalized Patreon entitlement, in the same shape as the service-to-service read.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Responses:** `200` with `user_hash`, `entitlement` (`external_source`, `status`,
    `plan_code`, `tier_code`, `tier_name`, `link_status`, `next_renewal_at`,
    `grace_period_until`, `last_synced_at`, `stale_after`, `classification_version`) and
    `contract_version`. An active user without Patreon data gets the `free` projection. `404`
    unknown or inactive user; `403` for non-root callers.
    """

    _require_root(log_context)
    safe_hash = str(user_hash or "").strip()
    if not safe_hash:
        raise ValidationError(message="user_hash is required", error_code=ErrorCode.INVALID_INPUT)
    row = db_patreon.get_entitlement_by_user_hash(safe_hash)
    if not row:
        raise NotFoundError(message="Patreon entitlement not found")
    response = patreon_sync.db_entitlement_row_to_s2s_response(row, user_hash=safe_hash, now=_utc_now())
    return _sanitize_patreon_admin_value(response.model_dump_safe(mode="json"))


@router.get("/entitlements/{user_hash}/history", responses=_ROOT_ONLY_403)
@log_and_handle_errors(
    operation_name="get_admin_patreon_entitlement_history",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def get_admin_patreon_entitlement_history(
    user_hash: Annotated[str, _USER_HASH_PATH],
    limit: int = Query(50, ge=1, le=200, description="Most recent transitions to return (1-200)."),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Return one user's recent Patreon entitlement transitions, newest first.

    Each row is a change of entitlement status, plan, tier or link status (or a tier-map
    miss), with the normalized `reason` and `sync_source` that caused it.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Responses:** `200` with `user_hash` and `items[]` (`history_id`, `previous_status`,
    `new_status`, `previous_plan_code`, `new_plan_code`, `previous_tier_code`, `new_tier_code`,
    `link_status`, `reason`, `sync_source`, `observed_at`). An unknown user returns an empty
    list. `403` for non-root callers.
    """

    _require_root(log_context)
    safe_hash = str(user_hash or "").strip()
    if not safe_hash:
        raise ValidationError(message="user_hash is required", error_code=ErrorCode.INVALID_INPUT)
    rows = db_patreon.list_patreon_entitlement_history_admin(user_hash=safe_hash, limit=limit)
    items = [
        PatreonAdminHistoryItem(
            history_id=str(row.get("history_id") or ""),
            previous_status=row.get("previous_status"),
            new_status=str(row.get("new_status") or "free"),
            previous_plan_code=row.get("previous_plan_code"),
            new_plan_code=str(row.get("new_plan_code") or "free"),
            previous_tier_code=row.get("previous_tier_code"),
            new_tier_code=row.get("new_tier_code"),
            link_status=row.get("link_status"),
            reason=str(row.get("reason") or "unknown")[:128],
            sync_source=str(row.get("sync_source") or "unknown"),
            observed_at=row.get("observed_at"),
        )
        for row in rows
        if row.get("history_id")
    ]
    response = PatreonAdminHistoryResponse(user_hash=safe_hash, items=items)
    return _sanitize_patreon_admin_value(response.model_dump_safe(mode="json"))


@router.get("/tier-map", responses=_ROOT_ONLY_403)
@log_and_handle_errors(
    operation_name="list_admin_patreon_tier_map",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_admin_patreon_tier_map(
    limit: int = Query(100, ge=1, le=500, description=_LIMIT_DESCRIPTION),
    offset: int = Query(0, ge=0, description=_OFFSET_DESCRIPTION),
    active: Optional[bool] = Query(None, description="Only active (`true`) or inactive (`false`) entries; omit for both."),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """List the stored Patreon tier map that turns campaign tiers into internal plan and tier codes.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Responses:** `200` with `items[]` ordered by priority — `campaign_fingerprint`,
    `campaign_name`, `tier_fingerprint`, `plan_code`, `tier_code`, `tier_name`, `priority`,
    `active`, `effective_from`, `effective_until` — and `pagination`. Campaign and tier ids appear
    only as fingerprints, never raw. `403` for non-root callers.

    The table mirrors the server-only tier-map configuration, which is what classifies users;
    it is refreshed from configuration before it is listed.
    """

    _require_root(log_context)
    try:
        config = load_patreon_config()
    except PatreonConfigError:
        config = None
    if config is not None and not getattr(config, "disabled", True):
        ensure_patreon_catalog_safely(config)
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


@router.get("/sync-jobs", responses=_ROOT_ONLY_403)
@log_and_handle_errors(
    operation_name="list_admin_patreon_sync_jobs",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_admin_patreon_sync_jobs(
    limit: int = Query(50, ge=1, le=500, description=_LIMIT_DESCRIPTION),
    offset: int = Query(0, ge=0, description=_OFFSET_DESCRIPTION),
    status: Optional[str] = Query(
        None,
        max_length=32,
        description="Exact job status: `pending`, `running`, `retry`, `completed`, `failed` or `cancelled`.",
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """List Patreon sync jobs queued for the sync worker, paginated.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Responses:** `200` with `items[]` (`job_id`, `job_type`, `status`, `priority`, `attempts`,
    `max_attempts`, `not_before`, `source`, timestamps and `has_error`) and `pagination`. Error
    text is reduced to the `has_error` flag. `403` for non-root callers.
    """

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


@router.get("/webhooks", responses=_ROOT_ONLY_403)
@log_and_handle_errors(
    operation_name="list_admin_patreon_webhooks",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False,
)
async def list_admin_patreon_webhooks(
    limit: int = Query(50, ge=1, le=500, description=_LIMIT_DESCRIPTION),
    offset: int = Query(0, ge=0, description=_OFFSET_DESCRIPTION),
    status: Optional[str] = Query(
        None,
        max_length=32,
        description=(
            "Exact delivery status: `received`, `processing`, `processed`, `rejected`, `replay`, "
            "`failed` or `ignored`."
        ),
    ),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """List recorded Patreon webhook deliveries, paginated, without payloads.

    Only deliveries whose signature verified are recorded; rejected signatures show up in the
    status endpoint's webhook counters instead.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Responses:** `200` with `items[]` (`delivery_id`, `event_type`, `status`,
    `signature_valid`, `received_at`, `processed_at`) and `pagination`. `403` for non-root callers.
    """

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


@router.post(
    "/resync",
    responses={
        **_ROOT_ONLY_403,
        404: {"description": "`scope` is `user` and no user has this `user_hash`."},
        429: {"description": "Resync enqueue rate limit exceeded; see `Retry-After`."},
    },
)
@log_and_handle_errors(
    operation_name="enqueue_admin_patreon_resync",
    activity_type=ActivityType.PATREON_SYNC_STARTED,
    log_success=True,
)
async def enqueue_admin_patreon_resync(
    scope: Literal["user", "all"] = Body(
        "user",
        description="`user` re-syncs one user's membership; `all` queues one full sweep of every configured campaign.",
    ),
    # Limits mirror PatreonAdminResyncRequest so they are enforced as request validation (400)
    # before the handler builds the model.
    user_hash: Optional[str] = Body(
        None, max_length=255, description="Public hash of the local user; required when `scope` is `user`."
    ),
    reason: Optional[str] = Body(
        None, max_length=128, description="Free-text note stored with the job (at most 128 characters)."
    ),
    force: bool = Body(False, description="Queue the job at higher priority."),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """Queue a Patreon source-of-truth resync for one user or for every configured campaign.

    **Auth:** root only — access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root user.

    **Request:** JSON object; every field is optional (`scope` defaults to `user`).

    **Responses:**
    - `200` `accepted: true`, `status: queued`, `correlation_id` (the job id). When an identical
      job is already queued the request is merged into it: `correlation_id` is that job's id and
      `message` says so. Queued jobs run only while the Patreon sync worker process is running.
    - `200` `accepted: false`, `status: disabled` when Patreon sync is turned off; nothing is queued.
    - `200` `accepted: false`, `status: not_linked` for `scope: user` when the user has no linked
      Patreon membership; nothing is queued.
    - `400` `scope: user` without `user_hash`, a `reason` over 128 characters, or a `user_hash`
      over 255; `404` unknown `user_hash`; `429` enqueue rate limit exceeded (`Retry-After`
      header); `403` for non-root callers.
    \f
    ``scope='user'`` goes through ``patreon_sync.enqueue_member_resync`` with the local user
    id (the worker scans configured campaigns for that user's linked membership).
    ``scope='all'`` writes a single full-campaign job with no campaign id, which the worker
    drains as a full sweep over every configured campaign. A limiter backend failure fails
    open (root-only route).
    """

    _require_root(log_context)
    payload = PatreonAdminResyncRequest(scope=scope, user_hash=user_hash, reason=reason, force=force)
    try:
        config = load_patreon_config()
    except PatreonConfigError:
        config = None
    if config is None or not bool(getattr(config, "sync_enabled", False)):
        return {
            "success": True,
            "accepted": False,
            "status": "disabled",
            "message": "Patreon sync is disabled." if config is not None else "Patreon configuration is invalid.",
        }

    safe_hash = str(payload.user_hash or "").strip()
    if payload.scope == "user" and not safe_hash:
        raise ValidationError(
            message="user_hash is required for scope='user'",
            error_code=ErrorCode.INVALID_INPUT,
        )

    try:
        _current_rate_limiter().check_sync_enqueue(
            kind=patreon_sync.JOB_TYPE_USER_MEMBER if payload.scope == "user" else patreon_sync.JOB_TYPE_FULL_CAMPAIGN,
            user_id=(safe_hash or "all"),
            source="admin",
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
        user = get_user_by_hash(safe_hash)
        if not user:
            raise NotFoundError(message="User not found")
        # A resync reads Patreon for the user's linked membership; without one there
        # is nothing to read, and the worker would page through every campaign.
        if not db_patreon.list_active_patreon_memberships(user_id=user.id):
            response = PatreonResyncAcceptedResponse(
                accepted=False,
                status="not_linked",
                user_hash=safe_hash,
                message="This user has no linked Patreon membership to resync.",
            )
            return _sanitize_patreon_admin_value(response.model_dump_safe(mode="json"))
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
    enqueued = db_patreon.enqueue_patreon_sync_job(
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
    queued_job_id, deduplicated = patreon_sync.enqueued_job_reference(enqueued, job_id)
    response = PatreonResyncAcceptedResponse(
        accepted=True,
        status="queued",
        correlation_id=queued_job_id,
        message=(
            "A full Patreon resync is already queued; this request was merged into it."
            if deduplicated
            else "Full Patreon resync enqueued."
        ),
    )
    return _sanitize_patreon_admin_value(response.model_dump_safe(mode="json"))


def _assert_admin_route_hardening() -> None:
    """Fail fast if the admin Patreon DTOs drift outside their safe allow-lists."""

    assert_patreon_response_model_allow_lists()


_assert_admin_route_hardening()
