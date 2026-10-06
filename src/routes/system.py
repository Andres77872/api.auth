"""
System Information Routes

Handles system information, health checks, monitoring endpoints, and cache management
for the group-based multi-project authentication system.
"""

import logging
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, HTTPException, Depends, Path
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import (
    SystemInfoResponse, HealthCheckResponse, PingResponse,
    CacheStatsResponse, ClearCacheResponse, InvalidateCacheResponse
)
from src.Util.security import HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors
from src.Util.log_context_models import LogContext
from src.Util.activity_logger import ActivityType
from src.Util.error_handler import AuthenticationError, AuthorizationError, ErrorCode, mask_uuid
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.cache_manager import cache_manager
from src.Util.system_metrics import SystemMetrics
from src.Util.db import (
    count_users, count_projects, count_user_groups,
    count_project_groups, validate_session, is_root_user, get_user_type
)

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/system", tags=["System Information"])
security = HTTPBearerOrCookie()


@router.get(
    "/info",
    response_model=SystemInfoResponse,
    responses={401: {"description": "Missing, invalid, expired, or revoked access token."}},
)
async def get_system_info(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> SystemInfoResponse:
    """
    Return service identity, aggregate tenant counts, and the advertised feature list.

    **Auth:** requires a valid access session: `Authorization: Bearer <access JWT>` or the
    `access_token` cookie. Any user type may call it; it is not a public endpoint.

    **Responses:** 200 with `system` (name, version, architecture, status), `statistics`
    (total users, projects, user groups, project groups) and `features`. Each count
    falls back to `0` if its query fails. Use `GET /system/ping` for an unauthenticated
    liveness probe.
    """
    # Require a valid session — tenant aggregate counts are not public.
    session_data = handle_db_operation(
        lambda: validate_session(credentials.credentials),
        error_context="session validation for system info"
    )
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    # Get basic system statistics (safely - all return 0 on error)
    total_users = handle_db_operation(
        lambda: count_users(),
        error_context="count users for system info",
        default_return=0
    )
    
    total_projects = handle_db_operation(
        lambda: count_projects(),
        error_context="count projects for system info",
        default_return=0
    )
    
    total_user_groups = handle_db_operation(
        lambda: count_user_groups(),
        error_context="count user groups for system info",
        default_return=0
    )
    
    total_project_groups = handle_db_operation(
        lambda: count_project_groups(),
        error_context="count project groups for system info",
        default_return=0
    )

    system_info = {
        "name": "Group-Based Multi-Project Authentication API",
        "version": "1.0.0",
        "architecture": "hierarchical-group-based",
        "status": "operational"
    }

    statistics = {
        "total_users": total_users,
        "total_projects": total_projects,
        "total_user_groups": total_user_groups,
        "total_project_groups": total_project_groups,
        "authentication_type": "group-based-jwt"
    }

    features = [
        "hierarchical-group-access-control",
        "global-user-groups",
        "project-permission-groups",
        "multi-project-support",
        "session-management-with-group-context",
        "comprehensive-audit-trail",
        "restful-admin-api"
    ]

    return SystemInfoResponse(
        success=True,
        system=system_info,
        statistics=statistics,
        features=features
    )


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    responses={401: {"description": (
        "Missing, invalid, expired, or revoked access token. Use `GET /system/ping` for credential-less probes."
    )}},
)
async def system_health(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> HealthCheckResponse:
    """
    Report per-component health (database, Redis, groups, email, Patreon, billing) and an overall status.

    **Auth:** requires a valid access session: `Authorization: Bearer <access JWT>` or the
    `access_token` cookie. Any user type may call it; it is not a public endpoint, so it
    cannot serve as a credential-less container/load-balancer probe (use `GET /system/ping`).

    **Responses:** a completed check returns 200 with `status` = `healthy` or `degraded`;
    component problems never change the HTTP status. `status` becomes `degraded` when:
    - the database or group-system query fails (that component reports `unhealthy`);
    - the Redis ping fails;
    - email delivery is enabled and the provider is not ready, the outbox is not
      `healthy`/`disabled`, or no email worker heartbeat is present (`email_worker`);
    - Patreon, or enabled billing (Stripe provider, webhooks, sync), reports
      `degraded`/`stale`/`retrying`/`unhealthy`/`not_ready`/`unknown`.

    Disabled email, Patreon or billing never degrade the result. Because authenticating
    the caller needs Redis and the database, an outage of either usually fails the request
    during authentication, before any component is checked.
    """
    # Require a valid session — infra/billing/email component health is not public.
    session_data = handle_db_operation(
        lambda: validate_session(credentials.credentials),
        error_context="session validation for system health"
    )
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    status = "healthy"
    timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    components = {}

    # Check database connectivity. default_return only applies when it is not None,
    # so the fallback is False: an outage must be reported, not raised as a 500.
    database_ok = handle_db_operation(
        lambda: count_users() is not None,
        error_context="database health check",
        default_return=False
    )
    if database_ok:
        components["database"] = {"status": "healthy", "message": "Database accessible"}
    else:
        components["database"] = {"status": "unhealthy", "message": "Database connection failed"}
        status = "degraded"

    # Check Redis connectivity
    def check_redis():
        from src.Util.db_config import redis_client
        redis_client.ping()
        return True
    
    redis_ok = handle_db_operation(
        check_redis,
        error_context="redis health check",
        default_return=False
    )
    if redis_ok:
        components["redis"] = {"status": "healthy", "message": "Redis accessible"}
    else:
        components["redis"] = {"status": "unhealthy", "message": "Redis connection failed"}
        status = "degraded"

    # Check group system
    def check_group_system():
        user_groups_count = count_user_groups()
        project_groups_count = count_project_groups()
        return {"user_groups": user_groups_count, "project_groups": project_groups_count}
    
    group_stats = handle_db_operation(
        check_group_system,
        error_context="group system health check",
        default_return={}
    )
    if group_stats:
        components["group_system"] = {
            "status": "healthy",
            "message": f"Group system operational: {group_stats['user_groups']} user groups, {group_stats['project_groups']} project groups"
        }
    else:
        components["group_system"] = {"status": "unhealthy", "message": "Group system check failed"}
        status = "degraded"

    # Email delivery health is additive and safe when disabled. A disabled or
    # not-ready email provider must not fail unrelated auth health checks.
    email_provider = SystemMetrics.get_email_provider_health()
    email_outbox = SystemMetrics.get_email_outbox_metrics()
    email_worker = SystemMetrics.get_email_worker_metrics()
    components["email_provider"] = email_provider
    components["email_outbox"] = email_outbox
    components["email_worker"] = email_worker

    if email_provider.get("delivery_enabled"):
        if (
            email_provider.get("ready") is not True
            or email_provider.get("status") != "ready"
            or email_outbox.get("status") not in {"healthy", "disabled"}
            or email_worker.get("status") != "healthy"
        ):
            status = "degraded"

    # Patreon is entitlement/link-only operational health. Keep it as a
    # separate component so local auth health remains independently observable;
    # disabled Patreon is safe and must not degrade unrelated auth checks.
    patreon = SystemMetrics.get_patreon_metrics()
    components["patreon"] = patreon
    if patreon.get("status") in {"degraded", "stale", "retrying", "unhealthy", "not_ready", "unknown"}:
        status = "degraded"

    # Billing/Stripe health is additive. Disabled or not-ready billing must not
    # degrade unrelated local auth/session health unless billing is explicitly
    # enabled and operationally unhealthy.
    billing = SystemMetrics.get_billing_metrics()
    billing_provider_stripe = (
        billing.get("provider_stripe")
        if isinstance(billing.get("provider_stripe"), dict)
        else SystemMetrics.get_billing_provider_stripe_health()
    )
    billing_webhooks = (
        billing.get("webhooks")
        if isinstance(billing.get("webhooks"), dict)
        else SystemMetrics.get_billing_webhook_metrics()
    )
    billing_sync = (
        billing.get("sync")
        if isinstance(billing.get("sync"), dict)
        else SystemMetrics.get_billing_sync_metrics()
    )
    components["billing"] = billing
    components["billing_provider_stripe"] = billing_provider_stripe
    components["billing_webhooks"] = billing_webhooks
    components["billing_sync"] = billing_sync

    billing_enabled = not bool(billing.get("readiness", {}).get("disabled", billing.get("status") == "disabled"))
    if billing_enabled and any(
        item in {"degraded", "stale", "retrying", "unhealthy", "not_ready", "unknown"}
        for item in (
            billing.get("status"),
            billing_provider_stripe.get("status"),
            billing_webhooks.get("status"),
            billing_sync.get("status"),
        )
    ):
        status = "degraded"

    return HealthCheckResponse(
        success=True,
        status=status,
        timestamp=timestamp,
        components=components
    )


@router.get("/ping", response_model=PingResponse)
async def ping() -> PingResponse:
    """
    Liveness probe: confirm the API process is answering.

    **Auth:** public; no credentials needed. Like every route, it still requires a
    `User-Agent` header (requests without one are rejected with 422 by middleware).

    **Responses:** always 200 with a fixed message and the current UTC timestamp. It does
    not touch the database, Redis, or any provider, so it is the right target for
    container and load-balancer health checks.
    """
    return PingResponse(
        success=True,
        message="Group-based authentication API is running",
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


@router.get("/cache/stats", response_model=CacheStatsResponse)
@log_and_handle_errors(
    operation_name="get_cache_stats",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_cache_statistics(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None
) -> CacheStatsResponse:
    """
    Return Redis key counts per authentication-cache namespace and the configured cache TTLs.

    **Auth:** any valid access token (`Authorization: Bearer <access JWT>` or `access_token`
    cookie); no user-type or permission check.

    **Responses:** 200 with `cache_statistics` (key counts for sessions, access checks,
    permission checks, user types, role checks, API keys, and total keys) and a static
    `cache_configuration` TTL summary. No hit-rate metrics are collected; if Redis cannot
    be read, `cache_statistics` is `{}`.
    """
    # Get cache statistics
    cache_stats = cache_manager.get_cache_stats()

    cache_config = {
        "session_ttl": "3600 seconds (1 hour)",
        "access_check_ttl": "1800 seconds (30 minutes)",
        "rbac_check_ttl": "1800 seconds (30 minutes)",
        "user_info_ttl": "3600 seconds (1 hour)"
    }

    return CacheStatsResponse(
        success=True,
        cache_statistics=cache_stats,
        cache_configuration=cache_config,
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


@router.post("/cache/clear", response_model=ClearCacheResponse)
@log_and_handle_errors(
    operation_name="clear_cache",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def clear_cache(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None
) -> ClearCacheResponse:
    """
    Delete every authentication-cache and access-session key in Redis.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `access_token` cookie)
    of a root or admin user; other users get 403.

    **Effect:** removes all `session:*`, `access:*`, `role:*`, `permission:*`, `user_info:*`
    and `user_type:*` keys. Deleting `session:*` revokes every live access session,
    including the caller's, so all clients must refresh or sign in again. Refresh
    families, rate-limit counters and API keys are not touched.

    **Responses:** 200 with a confirmation and warning; 500 if the Redis deletion fails.
    """
    # Check if user has admin permissions
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required to clear cache",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Clear entire cache
    success = cache_manager.clear_all_cache()

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to clear cache",
            error_code=ErrorCode.INTERNAL_ERROR
        )
    
    logger.warning(f"Cache cleared by user: {mask_uuid(log_context.user_hash)}")
    return ClearCacheResponse(
        success=True,
        message="Entire authentication cache has been cleared",
        cleared_by=mask_uuid(log_context.user_hash),
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        warning="All users will need to re-authenticate or may experience slower response times"
    )


@router.post("/cache/invalidate/user/{user_hash}", response_model=InvalidateCacheResponse)
@log_and_handle_errors(
    operation_name="invalidate_user_cache",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def invalidate_user_cache(
        user_hash: Annotated[str, Path(description="Public hash of the user whose cache entries are removed.")],
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> InvalidateCacheResponse:
    """
    Drop one user's cached access, permission, user-type and user-info entries, plus their access sessions.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `access_token` cookie)
    of a root or admin user; other users get 403.

    **Effect:** the user's `session:*`/`session_full:*` records are deleted as well, so
    their current access tokens stop validating until they refresh or sign in again.

    **Responses:** 200 with a confirmation; 404 if no user has that hash; 500 if the
    Redis operation fails.
    """
    # Check admin permissions
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Get user ID from hash
    from src.Util.db import get_user_by_hash
    target_user = handle_db_operation(
        lambda: get_user_by_hash(user_hash),
        error_context="user lookup",
        not_found_message=f"User not found: {mask_uuid(user_hash)}"
    )

    # Invalidate user cache; this endpoint also drops the user's access sessions
    success = cache_manager.invalidate_user_cache(target_user.id)
    cache_manager.invalidate_user_sessions(target_user.id)

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to invalidate user cache",
            error_code=ErrorCode.INTERNAL_ERROR
        )

    return InvalidateCacheResponse(
        success=True,
        message=f"Cache invalidated for user: {mask_uuid(user_hash)}",
        invalidated_by=mask_uuid(log_context.user_hash),
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )


@router.post("/cache/invalidate/project/{project_id}", response_model=InvalidateCacheResponse)
@log_and_handle_errors(
    operation_name="invalidate_project_cache",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=True
)
async def invalidate_project_cache(
        project_id: Annotated[str, Path(
            description=(
                "Project ID (`proj-...`) used to match cached `access:*`, `permission:*` and `role:*` keys. "
                "Letters, digits, `-` and `_` only (so it cannot widen the key pattern); anything else is rejected with 400."
            ),
            min_length=1,
            max_length=128,
            pattern=r"^[A-Za-z0-9_-]+$",
        )],
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> InvalidateCacheResponse:
    """
    Drop cached access, permission and role-check entries whose keys reference a project ID.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `access_token` cookie)
    of a root or admin user; other users get 403.

    **Responses:** 200 with a confirmation, even when no key matched (the project is not
    looked up); 500 if the Redis operation fails.
    """
    # Check admin permissions
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin permission required",
            error_code=ErrorCode.ACCESS_DENIED
        )

    # Invalidate project cache
    success = cache_manager.invalidate_project_cache(project_id)

    if not success:
        from src.Util.error_handler import InternalError
        raise InternalError(
            message="Failed to invalidate project cache",
            error_code=ErrorCode.INTERNAL_ERROR
        )

    return InvalidateCacheResponse(
        success=True,
        message=f"Cache invalidated for project: {project_id}",
        invalidated_by=mask_uuid(log_context.user_hash),
        timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
