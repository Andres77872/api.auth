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
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.db import (
    validate_session, count_users, count_projects, count_user_groups,
    count_active_sessions, get_recent_users_count, get_recent_projects_count,
    get_recent_activity_count, get_user_login_statistics, get_session_statistics
)
from src.Util.Models import BaseResponse
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db_config import get_connection, redis_client
from src.Util.activity_logger import count_activity_logs, get_recent_activity
from src.middleware.authentication import verify_admin_access

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
        raise HTTPException(status_code=401, detail="Invalid session")
    
    user_permissions = getattr(session_data, 'permissions', [])
    if 'admin' not in user_permissions:
        raise HTTPException(status_code=403, detail="Admin access required for analytics")
    
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
    try:
        # Get current totals
        total_users = count_users()
        total_projects = count_projects()
        active_sessions = count_active_sessions()
        
        # Get recent counts for the specified period
        recent_users = get_recent_users_count(days=period_days)
        recent_projects = get_recent_projects_count(days=period_days)
        recent_activities = get_recent_activity_count(days=period_days)
        
        # Get user type breakdown
        root_users = count_users(user_type='root')
        admin_users = count_users(user_type='admin')
        consumer_users = count_users(user_type='consumer')
        
        # Get session statistics
        session_stats = get_session_statistics()
        
        # Get login statistics for the period
        login_stats = get_user_login_statistics(days=period_days)
        
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
        
    except Exception as e:
        logger.error(f"Analytics dashboard stats error: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to get analytics dashboard statistics")


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
    try:
        # Get user counts by type
        total_users = count_users(user_type=user_type)
        recent_users = get_recent_users_count(days=period_days)
        
        # Get user type breakdown if no filter applied
        if not user_type:
            user_type_breakdown = {
                "root": count_users(user_type='root'),
                "admin": count_users(user_type='admin'),
                "consumer": count_users(user_type='consumer')
            }
        else:
            user_type_breakdown = {user_type: total_users}
        
        # Calculate registration trend (simplified daily average)
        daily_registration_rate = recent_users / period_days
        
        # Get user activity statistics
        login_stats = get_user_login_statistics(days=period_days)
        
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
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve user analytics: {str(e)}"
        )


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
    try:
        # Get project counts
        total_projects = count_projects()
        recent_projects = get_recent_projects_count(days=period_days)
        
        # Calculate project creation trend
        daily_project_creation_rate = recent_projects / period_days
        
        # Get project activity (activities related to projects)
        project_activities = count_activity_logs(days=period_days)
        
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
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve project analytics: {str(e)}"
        )


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
    try:
        # Get activity counts
        total_activities = count_activity_logs(
            days=period_days,
            activity_type=activity_type
        )
        
        # Get activity breakdown by type
        activity_breakdown = get_activity_type_breakdown(period_days)
        
        # Calculate activity metrics
        daily_avg_activities = total_activities / period_days
        
        # Get recent activity samples for pattern analysis
        recent_activities = get_recent_activity(
            limit=100,
            days=period_days,
            activity_type=activity_type
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
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve activity analytics: {str(e)}"
        )


@router.get("/summary")
async def get_analytics_summary(
    current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get high-level analytics summary
    
    Returns a comprehensive summary of all analytics for quick overview.
    """
    try:
        # Get quick stats for multiple periods
        stats_7d = {
            "users": get_recent_users_count(days=7),
            "projects": get_recent_projects_count(days=7),
            "activities": get_recent_activity_count(days=7)
        }
        
        stats_30d = {
            "users": get_recent_users_count(days=30),
            "projects": get_recent_projects_count(days=30),
            "activities": get_recent_activity_count(days=30)
        }
        
        # Get current totals
        current_totals = {
            "users": count_users(),
            "projects": count_projects(),
            "active_sessions": count_active_sessions()
        }
        
        # Get login statistics
        login_stats = get_user_login_statistics(days=7)
        
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
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve analytics summary: {str(e)}"
        )


# Helper function
def get_activity_type_breakdown(days: int) -> Dict[str, int]:
    """Get activity breakdown by type for the specified period"""
    try:
        # This is a simplified implementation
        # In a real implementation, you'd query the database for actual breakdown
        from src.Util.activity_logger import ActivityType
        
        breakdown = {}
        for activity_type in ActivityType:
            count = count_activity_logs(
                days=days,
                activity_type=activity_type.value
            )
            if count > 0:
                breakdown[activity_type.value] = count
        
        return breakdown
        
    except Exception:
        return {}


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def count_active_users() -> int:
    """Count active users (users who have logged in recently or have active sessions)"""
    try:
        with get_connection() as con:
            cur = con.cursor()
            # Since we don't have last_login field, count users with active sessions
            cur.execute("""
                SELECT COUNT(DISTINCT u.id) 
                FROM users u
                WHERE u.is_active = 1 
                AND EXISTS (
                    SELECT 1 FROM user_sessions us
                    JOIN user_projects up ON us.user_project_id = up.id 
                    WHERE up.user_id = u.id 
                    AND us.is_active = 1
                    AND us.expires_at > NOW()
                )
            """)
            result = cur.fetchone()
            return result[0] if result else 0
    except Exception:
        # Fallback: assume all active users if we can't determine
        return count_users()


def count_active_projects() -> int:
    """Count active projects"""
    try:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM projects 
                WHERE is_active = 1
            """)
            result = cur.fetchone()
            return result[0] if result else 0
    except Exception:
        return count_projects()


def count_active_sessions() -> int:
    """Count active sessions in Redis"""
    try:
        session_keys = redis_client.keys("session:*")
        return len(session_keys)
    except Exception:
        return 0


def get_recent_logins_count(days: int) -> int:
    """Get count of recent logins in the last N days"""
    try:
        # Use activity logs for login tracking
        from src.Util.activity_logger import count_activity_logs
        return count_activity_logs(activity_type='user_login', days=days)
    except Exception:
        # Fallback: estimate based on active sessions
        return min(count_active_sessions(), count_users())


def get_recent_registrations_count(days: int) -> int:
    """Get count of recent user registrations in the last N days"""
    try:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM users 
                WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                AND is_active = 1
            """, [days])
            result = cur.fetchone()
            return result[0] if result else 0
    except Exception:
        return 0


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
    login_score = min(recent_logins * 5, 50)      # Recent logins worth up to 50 points
    
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
    try:
        # Check database
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()
        
        # Check Redis
        redis_client.ping()
        
        return "healthy"
        
    except Exception:
        return "degraded" 