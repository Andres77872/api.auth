"""
Admin Dashboard Routes - Phase 1 Implementation

Provides endpoints for the admin dashboard including:
- Dashboard statistics
- Activity feed
- System health monitoring
"""

from datetime import datetime, timezone
import re
from typing import Annotated, Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Path, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.activity_logger import get_recent_activity, count_activity_logs, ActivityType, get_activity_by_id
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors
from src.Util.log_context_models import LogContext
from src.Util.error_handler import AuthorizationError, ErrorCode, NotFoundError, ValidationError
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.db import (
    count_users, count_projects, count_active_sessions,
    get_recent_users_count, get_recent_projects_count,
    get_recent_activity_count, check_database_health, check_redis_health,
    is_root_user, get_user_type, count_user_groups
)
from src.Util.db.db_project_groups import count_project_groups
# Imported as a module: the route handlers below reuse these helpers' names.
from src.Util import system_metrics

# Create router
router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])
security = HTTPBearerOrCookie()


@router.get("/dashboard/stats")
@log_and_handle_errors(
    operation_name="get_dashboard_stats",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_dashboard_stats(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Return headline counts for the admin dashboard.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user; other users get 403.

    **Responses:** 200 with `totals` (users, projects, user groups, project groups,
    active sessions, activities in the last 7 days), `recent_activity` and `growth`
    (new users/projects in the last 7 days, as counts rather than percentages),
    `user_breakdown` by user type, `groups_summary` averages and `system_health`
    (database and Redis status; `overall_status` is `healthy` only when both are healthy).
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    # Get basic counts
    total_users = count_users()
    total_projects = count_projects()
    active_sessions = count_active_sessions()
    
    # Get group counts (groups-of-groups architecture)
    total_user_groups = count_user_groups()
    total_project_groups = count_project_groups()

    # Get recent activity counts (last 7 days)
    recent_users = get_recent_users_count(days=7)
    recent_projects = get_recent_projects_count(days=7)
    recent_activity = get_recent_activity_count(days=7)

    # Get user type breakdown
    admin_users = count_users(user_type='admin')
    consumer_users = count_users(user_type='consumer')
    root_users = count_users(user_type='root')

    # Get system health
    db_health = check_database_health()
    redis_health = check_redis_health()

    # Calculate growth percentages (simplified - could be enhanced with historical data)
    user_growth = recent_users
    project_growth = recent_projects

    return {
        "totals": {
            "users": total_users,
            "projects": total_projects,
            "user_groups": total_user_groups,
            "project_groups": total_project_groups,
            "active_sessions": active_sessions,
            "recent_activities": recent_activity
        },
        "recent_activity": {
            "new_users_7d": recent_users,
            "new_projects_7d": recent_projects,
            "total_activities_7d": recent_activity
        },
        "user_breakdown": {
            "root_users": root_users,
            "admin_users": admin_users,
            "consumer_users": consumer_users
        },
        "groups_summary": {
            "total_user_groups": total_user_groups,
            "total_project_groups": total_project_groups,
            "avg_users_per_group": round(total_users / max(total_user_groups, 1), 2),
            "avg_projects_per_group": round(total_projects / max(total_project_groups, 1), 2)
        },
        "growth": {
            "user_growth_7d": user_growth,
            "project_growth_7d": project_growth
        },
        "system_health": {
            "database": db_health,
            "redis": redis_health,
            "overall_status": "healthy" if db_health["status"] == "healthy" and redis_health[
                "status"] == "healthy" else "degraded"
        },
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.get("/activity")
@log_and_handle_errors(
    operation_name="get_activity_feed",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_activity_feed(
        limit: int = Query(50, ge=1, le=500, description="Number of activities to return"),
        offset: int = Query(0, ge=0, description="Number of activities to skip"),
        activity_type_filter: Optional[str] = Query(
            None, description="Exact activity type (see `GET /admin/activity/types`)"
        ),
        user_id: Optional[str] = Query(None, description="Filter by acting user's internal ID (`usr-...`)"),
        project_id: Optional[str] = Query(None, description="Filter by internal project ID (`proj-...`)"),
        days: int = Query(30, ge=1, le=365, description="Days to look back"),
        search: Optional[str] = Query(None, description="Free-text search across activity_type, details, and username"),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    List activity-log entries, newest first, with filters and offset pagination.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user; other users get 403.

    **Request:** the activity-type filter is the `activity_type_filter` query parameter;
    an empty `search` is ignored.

    **Responses:** 200 with `activities` (each with `user`, `project` and `target_user`
    summaries or `null`), `pagination` (`total`, `has_more`, `next_offset`) and the echoed
    `filters`.
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    # Treat empty string as None (no filtering)
    search_param = search if search else None
    
    # Get recent activities with filters
    activities = get_recent_activity(
        limit=limit,
        offset=offset,
        user_id=user_id,
        project_id=project_id,
        activity_type=activity_type_filter,
        days=days,
        search=search_param,
    )

    # Get total count for pagination
    total_count = count_activity_logs(
        user_id=user_id,
        project_id=project_id,
        activity_type=activity_type_filter,
        days=days,
        search=search_param,
    )

    # Format activities for frontend
    formatted_activities = []
    for activity in activities:
        formatted_activity = {
                "id": activity["id"],
                "activity_type": activity["activity_type"],
                "details": activity["details"],
                "created_at": activity["created_at"].isoformat() + "Z" if hasattr(activity["created_at"], 'isoformat') else str(activity["created_at"]) + "Z",
                "user": {
                    "id": activity["user_id"],
                    "username": activity["username"],
                    "user_hash": activity["user_hash"]
                } if activity["user_id"] else None,
                "project": {
                    "id": activity["project_id"],
                    "name": activity["project_name"],
                    "hash": activity["project_hash"]
                } if activity["project_id"] else None,
                "target_user": {
                    "id": activity["target_user_id"],
                    "username": activity["target_username"],
                    "user_hash": activity["target_user_hash"]
                } if activity["target_user_id"] else None,
                "ip_address": activity["ip_address"]
        }
        formatted_activities.append(formatted_activity)

    # Calculate pagination info
    has_more = (offset + limit) < total_count
    next_offset = offset + limit if has_more else None

    return {
        "activities": formatted_activities,
        "pagination": {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "next_offset": next_offset
        },
        "filters": {
            "activity_type": activity_type_filter,
            "user_id": user_id,
            "project_id": project_id,
            "days": days,
            "search": search_param,
        },
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.get("/activity/types")
@log_and_handle_errors(
    operation_name="get_activity_types",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_activity_types(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    List every activity type the service defines, for building activity filters.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user; other users get 403.

    **Responses:** 200 with `activity_types`: all values of the server's activity-type
    enum, whether or not any entry of that type has been logged.
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    # Get activity types from enum
    activity_types = [activity_type.value for activity_type in ActivityType]

    return {
        "activity_types": activity_types,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.get("/activity/{activity_id}")
@log_and_handle_errors(
    operation_name="get_activity_detail",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_activity_detail(
        activity_id: Annotated[str, Path(description="Activity log ID: `act-` followed by 32 hex characters.")],
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Return one activity-log entry with all stored and enriched fields.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user; other users get 403.

    **Responses:** 200 with `activity` (type, details, severity, user/project/target
    summaries, IP, user agent, metadata and activity-type name/category/description);
    400 if the ID is not `act-` plus 32 hex characters; 404 if no entry has that ID.
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    # Validate activity_id format
    if not activity_id or not activity_id.strip():
        raise ValidationError(
            message="Invalid activity ID: empty value",
            error_code=ErrorCode.INVALID_INPUT,
        )
    
    # Validate activity_id matches expected format: act-{32 hex chars}
    if not re.match(r'^act-[0-9a-fA-F]{32}$', activity_id):
        raise ValidationError(
            message=f"Invalid activity ID format: {activity_id}",
            error_code=ErrorCode.INVALID_INPUT,
        )
    
    # Fetch activity by ID
    activity = get_activity_by_id(activity_id)
    
    if not activity:
        raise NotFoundError(
            message=f"Activity log entry not found: {activity_id}",
            error_code=ErrorCode.RESOURCE_NOT_FOUND,
        )
    
    # Format the activity for response
    formatted_activity = {
        "id": activity["id"],
        "activity_type": activity["activity_type"],
        "details": activity["details"],
        "severity_level": activity["severity_level"],
        "created_at": activity["created_at"].isoformat() + "Z" if hasattr(activity["created_at"], 'isoformat') else str(activity["created_at"]) + "Z",
        "user": {
            "id": activity["user_id"],
            "username": activity["username"],
            "user_hash": activity["user_hash"]
        } if activity["user_id"] else None,
        "project": {
            "id": activity["project_id"],
            "name": activity["project_name"],
            "hash": activity["project_hash"]
        } if activity["project_id"] else None,
        "target_user": {
            "id": activity["target_user_id"],
            "username": activity["target_username"],
            "user_hash": activity["target_user_hash"]
        } if activity["target_user_id"] else None,
        "ip_address": activity["ip_address"],
        "user_agent": activity["user_agent"],
        "metadata": activity["metadata"],
        "activity_name": activity["activity_name"],
        "activity_category": activity["activity_category"],
        "activity_description": activity["activity_description"],
    }
    
    return {
        "activity": formatted_activity,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.get("/health")
@log_and_handle_errors(
    operation_name="get_system_health",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_system_health(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Check database and Redis health and return a simple score for the admin dashboard.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user; other users get 403.

    **Responses:** 200 with `components` (database, redis), `metrics` (total users,
    projects, active sessions) and `health_score`: 100, minus 50 if the database check
    fails and 30 if Redis fails. `overall_status` is `healthy` at 100, `degraded` at 70
    or more, otherwise `unhealthy`. For the full component report see `GET /system/health`.
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    # Get health checks
    db_health = check_database_health()
    redis_health = check_redis_health()

    # Get system metrics
    total_users = count_users()
    total_projects = count_projects()
    active_sessions = count_active_sessions()

    # Calculate health score
    health_score = 100
    if db_health["status"] != "healthy":
        health_score -= 50
    if redis_health["status"] != "healthy":
        health_score -= 30

    # Determine overall status
    if health_score >= 100:
        overall_status = "healthy"
    elif health_score >= 70:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return {
        "overall_status": overall_status,
        "health_score": health_score,
        "components": {
            "database": db_health,
            "redis": redis_health
        },
        "metrics": {
            "total_users": total_users,
            "total_projects": total_projects,
            "active_sessions": active_sessions
        },
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.get("/users/statistics")
@log_and_handle_errors(
    operation_name="get_user_statistics",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_user_statistics(
        days: int = Query(30, ge=1, le=365, description="Days to look back for statistics"),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Return active-user counts by type plus new and active users over the last `days` days.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user; other users get 403.

    **Responses:** 200 with `statistics`: `total_users` and `user_types` (active users
    only), `new_users`, `active_users` (distinct users with activity-log entries),
    `growth_rate` and `activity_rate` (percentages). If the query fails, `statistics`
    holds only an `error` message.
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    stats = system_metrics.get_user_statistics(days)

    return {
        "success": True,
        "statistics": stats,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.get("/projects/statistics")
@log_and_handle_errors(
    operation_name="get_project_statistics",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_project_statistics(
        days: int = Query(30, ge=1, le=365, description="Days to look back for statistics"),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Return active-project counts, new and activity-bearing projects over the last `days` days, and average membership.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user; other users get 403.

    **Responses:** 200 with `statistics`: `total_projects` (active only), `new_projects`,
    `active_projects` (distinct projects with activity-log entries),
    `avg_members_per_project` and `utilization_rate` (percentage). If the query fails,
    `statistics` holds only an `error` message.
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    stats = system_metrics.get_project_statistics(days)

    return {
        "success": True,
        "statistics": stats,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }


@router.get("/system/overview")
@log_and_handle_errors(
    operation_name="get_system_overview",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_system_overview(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Return host resource usage, database/Redis health, application metrics, and Patreon and billing status.

    **Auth:** access token (`Authorization: Bearer <access JWT>` or `session_token`
    cookie) of a root or admin user; other users get 403.

    **Responses:** 200 with `system_overview`: `health_score` and `status` (`healthy` at
    80 or more, `degraded` at 60 or more, otherwise `unhealthy`), host CPU, memory, disk
    and uptime, database and Redis details, application metrics, and the Patreon and
    billing summaries. CPU usage is sampled over one second, so the call takes at least
    that long. On an internal failure the overview is `{"status": "error", "health_score": 0, ...}`.
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    overview = system_metrics.get_system_overview()

    return {
        "success": True,
        "system_overview": overview,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    }
