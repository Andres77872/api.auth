"""
Analytics Routes - Phase 1 Implementation

Provides endpoints for analytics data including:
- Dashboard statistics
- User analytics
- Project analytics
- Activity trends
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Models import BaseResponse
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import count_activity_logs, get_recent_activity
from src.Util.db import (
    validate_session, count_users, count_projects, count_active_sessions, get_recent_users_count,
    get_recent_projects_count,
    get_recent_activity_count, get_user_login_statistics, get_session_statistics
)
from src.Util.db_config import get_connection, redis_client
from src.middleware.authentication import verify_admin_access
from src.Util.error_handler import (
    AuthenticationError, AuthorizationError, InternalError, ErrorCode
)
from src.Util.db_error_wrapper import handle_db_operation

# Configure logging
logger = logging.getLogger(__name__)

# Initialize router and security
router = APIRouter(prefix="/analytics", tags=["Analytics"])
security = HTTPBearerOrCookie()


class AnalyticsDashboardStatsResponse(BaseResponse):
    """Analytics dashboard statistics response"""
    analytics: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None
    generated_at: Optional[str] = None


def require_admin_access(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Ensure user has admin access for analytics"""
    session_data = validate_session(credentials.credentials)
    if not session_data:
        raise AuthenticationError(
            message="Invalid or expired session",
            error_code=ErrorCode.SESSION_INVALID
        )

    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions:
        raise AuthorizationError(
            message="Admin access required for analytics",
            error_code=ErrorCode.INSUFFICIENT_PERMISSIONS,
            details={"required_permission": "admin"}
        )

    return session_data


@router.get("/dashboard/stats", response_model=AnalyticsDashboardStatsResponse)
async def get_analytics_dashboard_stats(
        period_days: int = Query(30, ge=1, le=365, description="Days to analyze"),
        current_user: dict = Depends(verify_admin_access)
) -> AnalyticsDashboardStatsResponse:
    """
    Get basic analytics for dashboard
    
    Returns analytics data for the specified time period including:
    - User metrics and trends
    - Project metrics and growth
    - Activity metrics and patterns
    - System performance indicators
    """
    # Get current totals (safely wrapped)
    total_users = handle_db_operation(
        lambda: count_users(),
        error_context="count users for analytics",
        default_return=0
    )
    total_projects = handle_db_operation(
        lambda: count_projects(),
        error_context="count projects for analytics",
        default_return=0
    )
    active_sessions = handle_db_operation(
        lambda: count_active_sessions(),
        error_context="count active sessions for analytics",
        default_return=0
    )

    # Get recent counts for the specified period
    recent_users = handle_db_operation(
        lambda: get_recent_users_count(days=period_days),
        error_context="get recent users count",
        default_return=0
    )
    recent_projects = handle_db_operation(
        lambda: get_recent_projects_count(days=period_days),
        error_context="get recent projects count",
        default_return=0
    )
    recent_activities = handle_db_operation(
        lambda: get_recent_activity_count(days=period_days),
        error_context="get recent activity count",
        default_return=0
    )

    # Get user type breakdown
    root_users = handle_db_operation(
        lambda: count_users(user_type='root'),
        error_context="count root users",
        default_return=0
    )
    admin_users = handle_db_operation(
        lambda: count_users(user_type='admin'),
        error_context="count admin users",
        default_return=0
    )
    consumer_users = handle_db_operation(
        lambda: count_users(user_type='consumer'),
        error_context="count consumer users",
        default_return=0
    )

    # Get session statistics
    session_stats = handle_db_operation(
        lambda: get_session_statistics(),
        error_context="get session statistics",
        default_return={}
    )

    # Get login statistics for the period
    login_stats = handle_db_operation(
        lambda: get_user_login_statistics(days=period_days),
        error_context="get login statistics",
        default_return={}
    )

    # Calculate growth rates (simplified)
    user_growth_rate = (recent_users / max(total_users - recent_users, 1)) * 100
    project_growth_rate = (recent_projects / max(total_projects - recent_projects, 1)) * 100

    # Get activity breakdown by type
    activity_breakdown = get_activity_type_breakdown(period_days)

    # Build analytics data
    analytics = {
        "period": {
            "days": period_days,
            "start_date": (datetime.utcnow() - timedelta(days=period_days)).isoformat(),
            "end_date": datetime.utcnow().isoformat()
        },
        "user_metrics": {
            "total_users": total_users,
            "new_users": recent_users,
            "growth_rate": round(user_growth_rate, 2),
            "user_types": {
                "root": root_users,
                "admin": admin_users,
                "consumer": consumer_users
            }
        },
        "project_metrics": {
            "total_projects": total_projects,
            "new_projects": recent_projects,
            "growth_rate": round(project_growth_rate, 2)
        },
        "activity_metrics": {
            "total_activities": recent_activities,
            "activities_per_day": round(recent_activities / period_days, 2),
            "activity_breakdown": activity_breakdown
        },
        "session_metrics": {
            "active_sessions": active_sessions,
            "session_stats": session_stats
        },
        "login_metrics": login_stats
    }

    # Generate summary
    summary = {
        "total_entities": total_users + total_projects,
        "activity_score": calculate_activity_score(recent_activities, recent_users),
        "growth_trend": calculate_growth_trend(recent_users),
        "health_status": "healthy" if active_sessions < 1000 and total_users > 0 else "monitoring"
    }

    return AnalyticsDashboardStatsResponse(
        success=True,
        analytics=analytics,
        summary=summary,
        generated_at=datetime.utcnow().isoformat()
    )


@router.get("/users")
async def get_user_analytics(
        period_days: int = Query(30, ge=1, le=365, description="Days to analyze"),
        user_type: Optional[str] = Query(None, description="Filter by user type"),
        current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get detailed user analytics
    
    Returns comprehensive user analytics including:
    - User registration trends
    - User type distribution
    - User activity patterns
    """
    # Get user counts by type (safely wrapped)
    total_users = handle_db_operation(
        lambda: count_users(user_type=user_type),
        error_context="count users by type",
        default_return=0
    )
    recent_users = handle_db_operation(
        lambda: get_recent_users_count(days=period_days),
        error_context="get recent users count",
        default_return=0
    )

    # Get user type breakdown if no filter applied
    if not user_type:
        user_type_breakdown = {
            "root": handle_db_operation(lambda: count_users(user_type='root'), error_context="count root users", default_return=0),
            "admin": handle_db_operation(lambda: count_users(user_type='admin'), error_context="count admin users", default_return=0),
            "consumer": handle_db_operation(lambda: count_users(user_type='consumer'), error_context="count consumer users", default_return=0)
        }
    else:
        user_type_breakdown = {user_type: total_users}

    # Calculate registration trend (simplified daily average)
    daily_registration_rate = recent_users / period_days

    # Get user activity statistics
    login_stats = handle_db_operation(
        lambda: get_user_login_statistics(days=period_days),
        error_context="get login statistics",
        default_return={}
    )

    return {
        "period": {
            "days": period_days,
            "start_date": (datetime.utcnow() - timedelta(days=period_days)).isoformat(),
            "end_date": datetime.utcnow().isoformat()
        },
        "user_totals": {
            "total_users": total_users,
            "new_users_period": recent_users,
            "daily_avg_registrations": round(daily_registration_rate, 2)
        },
        "user_type_breakdown": user_type_breakdown,
        "activity_patterns": {
            "login_statistics": login_stats,
            "avg_logins_per_day": round(login_stats.get("total_logins", 0) / period_days, 2)
        },
        "trends": {
            "registration_trend": "increasing" if daily_registration_rate > 0.5 else "stable",
            "activity_trend": "active" if login_stats.get("unique_users", 0) > (total_users * 0.3) else "moderate"
        },
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/projects")
async def get_project_analytics(
        period_days: int = Query(30, ge=1, le=365, description="Days to analyze"),
        current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get detailed project analytics
    
    Returns comprehensive project analytics including:
    - Project creation trends
    - Project activity levels
    - User engagement per project
    """
    # Get project counts (safely wrapped)
    total_projects = handle_db_operation(
        lambda: count_projects(),
        error_context="count projects",
        default_return=0
    )
    recent_projects = handle_db_operation(
        lambda: get_recent_projects_count(days=period_days),
        error_context="get recent projects count",
        default_return=0
    )

    # Calculate project creation trend
    daily_project_creation_rate = recent_projects / period_days

    # Get project activity (activities related to projects)
    project_activities = handle_db_operation(
        lambda: count_activity_logs(days=period_days),
        error_context="count activity logs",
        default_return=0
    )

    # Calculate project engagement metrics
    avg_activities_per_project = project_activities / max(total_projects, 1)

    return {
        "period": {
            "days": period_days,
            "start_date": (datetime.utcnow() - timedelta(days=period_days)).isoformat(),
            "end_date": datetime.utcnow().isoformat()
        },
        "project_totals": {
            "total_projects": total_projects,
            "new_projects_period": recent_projects,
            "daily_avg_creation": round(daily_project_creation_rate, 2)
        },
        "activity_metrics": {
            "total_project_activities": project_activities,
            "avg_activities_per_project": round(avg_activities_per_project, 2),
            "activities_per_day": round(project_activities / period_days, 2)
        },
        "trends": {
            "creation_trend": "increasing" if daily_project_creation_rate > 0.1 else "stable",
            "activity_trend": "high" if avg_activities_per_project > 10 else "moderate"
        },
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/activity")
async def get_activity_analytics(
        period_days: int = Query(30, ge=1, le=365, description="Days to analyze"),
        activity_type: Optional[str] = Query(None, description="Filter by activity type"),
        current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get detailed activity analytics
    
    Returns comprehensive activity analytics including:
    - Activity volume trends
    - Activity type distribution
    - Peak activity periods
    """
    # Get activity counts (safely wrapped)
    total_activities = handle_db_operation(
        lambda: count_activity_logs(days=period_days, activity_type=activity_type),
        error_context="count activity logs",
        default_return=0
    )

    # Get activity breakdown by type
    activity_breakdown = get_activity_type_breakdown(period_days)

    # Calculate activity metrics
    daily_avg_activities = total_activities / period_days

    # Get recent activity samples for pattern analysis
    recent_activities = handle_db_operation(
        lambda: get_recent_activity(limit=100, days=period_days, activity_type=activity_type),
        error_context="get recent activity",
        default_return=[]
    )

    # Analyze activity patterns (simplified)
    unique_users_active = len(set(
        activity.get("user_id") for activity in recent_activities
        if activity.get("user_id")
    ))

    unique_projects_active = len(set(
        activity.get("project_id") for activity in recent_activities
        if activity.get("project_id")
    ))

    return {
        "period": {
            "days": period_days,
            "start_date": (datetime.utcnow() - timedelta(days=period_days)).isoformat(),
            "end_date": datetime.utcnow().isoformat()
        },
        "activity_totals": {
            "total_activities": total_activities,
            "daily_avg_activities": round(daily_avg_activities, 2),
            "filtered_by_type": activity_type
        },
        "activity_breakdown": activity_breakdown,
        "engagement_metrics": {
            "unique_active_users": unique_users_active,
            "unique_active_projects": unique_projects_active,
            "activities_per_user": round(total_activities / max(unique_users_active, 1), 2)
        },
        "trends": {
            "volume_trend": "high" if daily_avg_activities > 50 else "moderate",
            "engagement_trend": "active" if unique_users_active > 10 else "moderate"
        },
        "generated_at": datetime.utcnow().isoformat()
    }


@router.get("/summary")
async def get_analytics_summary(
        current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get high-level analytics summary
    
    Returns a comprehensive summary of all analytics for quick overview.
    """
    # Get quick stats for multiple periods (safely wrapped)
    stats_7d = {
        "users": handle_db_operation(lambda: get_recent_users_count(days=7), error_context="recent users 7d", default_return=0),
        "projects": handle_db_operation(lambda: get_recent_projects_count(days=7), error_context="recent projects 7d", default_return=0),
        "activities": handle_db_operation(lambda: get_recent_activity_count(days=7), error_context="recent activities 7d", default_return=0)
    }

    stats_30d = {
        "users": handle_db_operation(lambda: get_recent_users_count(days=30), error_context="recent users 30d", default_return=0),
        "projects": handle_db_operation(lambda: get_recent_projects_count(days=30), error_context="recent projects 30d", default_return=0),
        "activities": handle_db_operation(lambda: get_recent_activity_count(days=30), error_context="recent activities 30d", default_return=0)
    }

    # Get current totals
    current_totals = {
        "users": handle_db_operation(lambda: count_users(), error_context="count users", default_return=0),
        "projects": handle_db_operation(lambda: count_projects(), error_context="count projects", default_return=0),
        "active_sessions": handle_db_operation(lambda: count_active_sessions(), error_context="count sessions", default_return=0)
    }

    # Get login statistics
    login_stats = handle_db_operation(
        lambda: get_user_login_statistics(days=7),
        error_context="get login statistics",
        default_return={}
    )

    return {
        "current_totals": current_totals,
        "recent_activity": {
            "last_7_days": stats_7d,
            "last_30_days": stats_30d
        },
        "login_metrics": login_stats,
        "growth_indicators": {
            "weekly_user_growth": stats_7d["users"],
            "weekly_project_growth": stats_7d["projects"],
            "weekly_activity_volume": stats_7d["activities"]
        },
        "generated_at": datetime.utcnow().isoformat()
    }


# Helper function
def get_activity_type_breakdown(days: int) -> Dict[str, int]:
    """Get activity breakdown by type for the specified period"""
    # This is a simplified implementation
    # In a real implementation, you'd query the database for actual breakdown
    from src.Util.activity_logger import ActivityType

    breakdown = {}
    for activity_type in ActivityType:
        count = handle_db_operation(
            lambda at=activity_type: count_activity_logs(days=days, activity_type=at.value),
            error_context=f"count activity logs for {activity_type.value}",
            default_return=0
        )
        if count > 0:
            breakdown[activity_type.value] = count

    return breakdown


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def count_active_users() -> int:
    """Count active users (users who have logged in recently or have active sessions)"""
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            # Since we don't have last_login field, count users with active sessions
            cur.execute("""
                        SELECT COUNT(DISTINCT u.id)
                        FROM users u
                        WHERE u.is_active = 1
                          AND EXISTS (SELECT 1
                                      FROM user_sessions us
                                               JOIN user_projects up ON us.user_project_id = up.id
                                      WHERE up.user_id = u.id
                                        AND us.is_active = 1
                                        AND us.expires_at > NOW())
                        """)
            result = cur.fetchone()
            return result[0] if result else 0
    
    # Fallback: assume all active users if we can't determine
    return handle_db_operation(_count, error_context="count active users", default_return=lambda: count_users())


def count_active_projects() -> int:
    """Count active projects"""
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                        SELECT COUNT(*)
                        FROM projects
                        WHERE is_active = 1
                        """)
            result = cur.fetchone()
            return result[0] if result else 0
    
    return handle_db_operation(_count, error_context="count active projects", default_return=lambda: count_projects())


def count_active_sessions() -> int:
    """Count active sessions in Redis"""
    def _count():
        session_keys = redis_client.keys("session:*")
        return len(session_keys)
    
    return handle_db_operation(_count, error_context="count active sessions", default_return=0)


def get_recent_logins_count(days: int) -> int:
    """Get count of recent logins in the last N days"""
    def _count():
        # Use activity logs for login tracking
        from src.Util.activity_logger import count_activity_logs
        return count_activity_logs(activity_type='user_login', days=days)
    
    # Fallback: estimate based on active sessions
    return handle_db_operation(_count, error_context="count recent logins", default_return=lambda: min(count_active_sessions(), count_users()))


def get_recent_registrations_count(days: int) -> int:
    """Get count of recent user registrations in the last N days"""
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                        SELECT COUNT(*)
                        FROM users
                        WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                          AND is_active = 1
                        """, [days])
            result = cur.fetchone()
            return result[0] if result else 0
    
    return handle_db_operation(_count, error_context="count recent registrations", default_return=0)


def calculate_project_utilization(total_projects: int, active_users: int) -> float:
    """Calculate project utilization percentage"""
    if total_projects == 0:
        return 0.0

    # Simple utilization: assume each active user uses at least one project
    utilization = min(active_users / total_projects, 1.0) * 100
    return round(utilization, 2)


def calculate_activity_score(active_sessions: int, recent_logins: int) -> int:
    """Calculate overall activity score (0-100)"""
    # Basic activity scoring
    session_score = min(active_sessions * 2, 50)  # Sessions worth up to 50 points
    login_score = min(recent_logins * 5, 50)  # Recent logins worth up to 50 points

    return min(session_score + login_score, 100)


def calculate_growth_trend(recent_registrations: int) -> str:
    """Calculate growth trend based on recent registrations"""
    if recent_registrations == 0:
        return "stable"
    elif recent_registrations <= 2:
        return "slow_growth"
    elif recent_registrations <= 10:
        return "moderate_growth"
    else:
        return "high_growth"


def get_basic_system_health() -> str:
    """Get basic system health status"""
    def _check():
        # Check database
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()

        # Check Redis
        redis_client.ping()

        return "healthy"
    
    return handle_db_operation(_check, error_context="check system health", default_return="degraded")
