"""
Admin Dashboard Routes - Phase 1 Implementation

Provides endpoints for the admin dashboard including:
- Dashboard statistics
- Activity feed
- System health monitoring
"""

from datetime import datetime
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.activity_logger import get_recent_activity, count_activity_logs, ActivityType
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors
from src.Util.log_context_models import LogContext
from src.Util.error_handler import AuthorizationError, ErrorCode
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.db import (
    count_users, count_projects, count_active_sessions,
    get_recent_users_count, get_recent_projects_count,
    get_recent_activity_count, check_database_health, check_redis_health,
    is_root_user, get_user_type, count_user_groups
)
from src.Util.db.db_project_groups import count_project_groups
from src.Util.system_metrics import get_user_statistics, get_project_statistics, get_system_overview

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
    Get main dashboard statistics
    
    Returns comprehensive statistics for the admin dashboard including:
    - Total counts (users, projects, sessions)
    - Recent activity counts
    - System health status
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
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/activity")
@log_and_handle_errors(
    operation_name="get_activity_feed",
    activity_type=ActivityType.ADMIN_ACTION,
    log_success=False
)
async def get_activity_feed(
        limit: int = Query(50, ge=1, le=100, description="Number of activities to return"),
        offset: int = Query(0, ge=0, description="Number of activities to skip"),
        activity_type_filter: Optional[str] = Query(None, description="Filter by activity type"),
        user_id: Optional[str] = Query(None, description="Filter by user ID"),
        project_id: Optional[str] = Query(None, description="Filter by project ID"),
        days: int = Query(30, ge=1, le=365, description="Days to look back"),
        credentials: HTTPAuthorizationCredentials = Depends(security),
        log_context: LogContext = None
) -> Dict[str, Any]:
    """
    Get activity feed for the dashboard
    
    Returns recent activities with pagination and filtering options.
    Supports filtering by activity type, user, project, and time range.
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    # Get recent activities with filters
    activities = get_recent_activity(
        limit=limit,
        offset=offset,
        user_id=user_id,
        project_id=project_id,
        activity_type=activity_type_filter,
        days=days
    )

    # Get total count for pagination
    total_count = count_activity_logs(
        user_id=user_id,
        project_id=project_id,
        activity_type=activity_type_filter,
        days=days
    )

    # Format activities for frontend
    formatted_activities = []
    for activity in activities:
        formatted_activity = {
                "id": activity["id"],
                "activity_type": activity["activity_type"],
                "details": activity["details"],
                "created_at": activity["created_at"],
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
            "days": days
        },
        "generated_at": datetime.utcnow().isoformat()
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
    Get detailed system health information
    
    Returns comprehensive system health data including:
    - Database connectivity and status
    - Redis connectivity and status
    - System metrics and performance indicators
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
        "checked_at": datetime.utcnow().isoformat()
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
    Get available activity types for filtering
    
    Returns list of all activity types that have been logged in the system.
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
        "generated_at": datetime.utcnow().isoformat()
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
    Get detailed user statistics for admin dashboard
    
    Phase 2 Implementation: User statistics with breakdown and growth rates
    
    Args:
        days: Number of days to look back for growth calculations
        
    Returns:
        Comprehensive user statistics including type breakdown and growth
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    stats = get_user_statistics(days)

    return {
        "success": True,
        "statistics": stats,
        "generated_at": datetime.utcnow().isoformat()
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
    Get detailed project statistics for admin dashboard
    
    Phase 2 Implementation: Project statistics and health metrics
    
    Args:
        days: Number of days to look back for analytics
        
    Returns:
        Project counts, member averages, most active projects
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    stats = get_project_statistics(days)

    return {
        "success": True,
        "statistics": stats,
        "generated_at": datetime.utcnow().isoformat()
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
    Get comprehensive system health and performance overview
    
    Phase 2 Implementation: System health with uptime, database status, cache status, API metrics
    
    Returns:
        Complete system overview including health scores and performance metrics
    """
    # Check admin access
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED
        )
    
    overview = get_system_overview()

    return {
        "success": True,
        "system_overview": overview,
        "generated_at": datetime.utcnow().isoformat()
    }
