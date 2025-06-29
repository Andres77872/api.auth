"""
Admin Dashboard Routes

Handles admin dashboard functionality including statistics, activity logs,
and system monitoring for the multi-project authentication system.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.db import (
    validate_session, get_user_by_hash, count_users, count_projects,
    count_user_groups, list_users, list_all_projects, count_active_sessions,
    get_session_statistics, check_database_health, check_redis_health,
    get_recent_activity_count, get_recent_users_count, get_recent_projects_count
)
from src.Util.activity_logger import get_recent_activity, count_activity_logs
from src.Util.Models import BaseResponse, PaginationInfo
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db_config import get_connection, redis_client

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/admin/dashboard", tags=["Admin Dashboard"])
security = HTTPBearerOrCookie()


class DashboardStatsResponse(BaseResponse):
    """Dashboard statistics response"""
    statistics: Optional[Dict[str, Any]] = None
    system_health: Optional[Dict[str, Any]] = None
    recent_activity: Optional[Dict[str, Any]] = None


class ActivityResponse(BaseResponse):
    """Activity feed response"""
    activities: List[Dict[str, Any]] = []
    pagination: Optional[PaginationInfo] = None
    filters: Optional[Dict[str, Any]] = None


def require_admin_access(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin access for dashboard"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions:
        raise HTTPException(status_code=403, detail="Admin access required for dashboard")
    
    return session_data


@router.get("/stats", response_model=DashboardStatsResponse)
async def get_dashboard_statistics(
    session_data = Depends(require_admin_access)
) -> DashboardStatsResponse:
    """
    Get comprehensive dashboard statistics for admin users.
    
    **Admin access required**: Only admin users can access dashboard statistics.
    
    Returns:
        Dashboard statistics including user counts, project stats, and system health
    """
    try:
        # Get basic counts
        total_users = count_users()
        total_projects = count_projects()
        total_user_groups = count_user_groups()
        
        # Get user type breakdown
        root_users = count_users(user_type='root')
        admin_users = count_users(user_type='admin')
        consumer_users = count_users(user_type='consumer')
        
        # Get active session count
        active_sessions = count_active_sessions()
        
        # Get recent registrations (last 30 days)
        recent_users = get_recent_users_count(30)
        recent_projects = get_recent_projects_count(30)
        
        # Build statistics
        statistics = {
            "users": {
                "total": total_users,
                "root_users": root_users,
                "admin_users": admin_users,
                "consumer_users": consumer_users,
                "recent_registrations": recent_users
            },
            "projects": {
                "total": total_projects,
                "recent_projects": recent_projects
            },
            "groups": {
                "user_groups": total_user_groups
            },
            "activity": {
                "active_sessions": active_sessions,
                "session_health": "healthy" if active_sessions < 1000 else "high_load"
            }
        }
        
        # Check system health
        system_health = {
            "database": check_database_health(),
            "redis": check_redis_health(),
            "overall_status": "healthy"
        }
        
        # If any component is unhealthy, mark overall as degraded
        if not all(system_health[k].get("status") == "healthy" for k in ["database", "redis"]):
            system_health["overall_status"] = "degraded"
        
        # Get recent activity summary
        recent_activity = {
            "total_recent_activities": get_recent_activity_count(7),
            "login_attempts_today": get_login_attempts_today(),
            "failed_logins_today": get_failed_logins_today(),
            "new_users_today": get_new_users_today()
        }
        
        return DashboardStatsResponse(
            success=True,
            statistics=statistics,
            system_health=system_health,
            recent_activity=recent_activity
        )
        
    except Exception as e:
        logger.error(f"Dashboard statistics error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get dashboard statistics")


@router.get("/activity", response_model=ActivityResponse)
async def get_activity_feed(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    activity_type: Optional[str] = Query(None),
    user_hash: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=30),
    session_data = Depends(require_admin_access)
) -> ActivityResponse:
    """
    Get activity feed for admin dashboard.
    
    **Admin access required**: Only admin users can access activity feed.
    
    Args:
        limit: Number of activities to return
        offset: Number of activities to skip
        activity_type: Filter by activity type
        user_hash: Filter by specific user
        days: Number of days to look back
        
    Returns:
        Activity feed with pagination
    """
    try:
        # Get activities from the last N days
        since_date = datetime.utcnow() - timedelta(days=days)
        
        # Convert user_hash to user_id if provided
        user_id = None
        if user_hash:
            from src.Util.db import get_user_by_hash
            user = get_user_by_hash(user_hash)
            user_id = user.id if user else None
        
        activities = get_recent_activity(
            limit=limit,
            offset=offset,
            user_id=user_id,
            activity_type=activity_type,
            days=days
        )
        
        total_count = count_activity_logs(
            user_id=user_id,
            activity_type=activity_type,
            days=days
        )
        
        pagination = PaginationInfo(
            limit=limit,
            offset=offset,
            total=total_count,
            has_more=offset + limit < total_count
        )
        
        filters_info = {
            "activity_type": activity_type,
            "user_hash": user_hash,
            "days": days,
            "since_date": since_date.isoformat()
        }
        
        return ActivityResponse(
            success=True,
            activities=activities,
            pagination=pagination,
            filters=filters_info
        )
        
    except Exception as e:
        logger.error(f"Activity feed error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get activity feed")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def get_login_attempts_today() -> int:
    """Get login attempts for today (placeholder implementation)"""
    # This would query actual login logs when implemented
    return get_login_attempts_count(1)


def get_failed_logins_today() -> int:
    """Get failed login attempts for today (placeholder implementation)"""
    # This would query actual failed login logs when implemented
    return int(get_login_attempts_today() * 0.05)  # Assume 5% failure rate


def get_new_users_today() -> int:
    """Get new users registered today"""
    return get_recent_users_count(1)


def get_login_attempts_count(days: int) -> int:
    """Get estimated login attempts based on active sessions"""
    try:
        # Estimate based on active sessions and user count
        active_sessions = count_active_sessions()
        total_users = count_users()
        if total_users > 0:
            return int(active_sessions * 1.5)  # Rough estimate
        return 0
    except Exception:
        return 0


# Activity logging functions are now handled by the activity_logger module 