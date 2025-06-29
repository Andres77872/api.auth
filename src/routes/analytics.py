"""
Analytics Routes

Handles basic analytics functionality for the multi-project authentication system.
This is the Phase 1 foundation implementation providing basic metrics.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.db import (
    validate_session, count_users, count_projects, count_user_groups
)
from src.Util.Models import BaseResponse
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.db_config import get_connection, redis_client

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
    session_data = Depends(require_admin_access)
) -> AnalyticsDashboardStatsResponse:
    """
    Get basic analytics statistics for dashboard.
    
    **Admin access required**: Only admin users can access analytics data.
    
    This is the Phase 1 basic analytics implementation providing simple metrics
    for users, projects, and basic activity information.
    
    Returns:
        Basic analytics metrics including user counts, project stats, and activity summary
    """
    try:
        # Get basic user statistics
        total_users = count_users()
        root_users = count_users(user_type='root')
        admin_users = count_users(user_type='admin')  
        consumer_users = count_users(user_type='consumer')
        active_users = count_active_users()
        
        # Get project statistics
        total_projects = count_projects()
        active_projects = count_active_projects()
        
        # Get group statistics
        total_user_groups = count_user_groups()
        
        # Get activity metrics
        active_sessions = count_active_sessions()
        recent_logins_7d = get_recent_logins_count(7)
        recent_registrations_7d = get_recent_registrations_count(7)
        
        # Build analytics data
        analytics = {
            "user_metrics": {
                "total_users": total_users,
                "active_users": active_users,
                "user_breakdown": {
                    "root_users": root_users,
                    "admin_users": admin_users,
                    "consumer_users": consumer_users
                },
                "activity": {
                    "recent_logins_7d": recent_logins_7d,
                    "recent_registrations_7d": recent_registrations_7d
                }
            },
            "project_metrics": {
                "total_projects": total_projects,
                "active_projects": active_projects,
                "project_utilization": calculate_project_utilization(total_projects, active_users)
            },
            "system_metrics": {
                "total_user_groups": total_user_groups,
                "active_sessions": active_sessions,
                "system_health": get_basic_system_health()
            }
        }
        
        # Generate summary
        summary = {
            "total_entities": total_users + total_projects + total_user_groups,
            "activity_score": calculate_activity_score(active_sessions, recent_logins_7d),
            "growth_trend": calculate_growth_trend(recent_registrations_7d),
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


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def count_active_users() -> int:
    """Count active users (users who have logged in recently or have active sessions)"""
    try:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                SELECT COUNT(DISTINCT u.user_id) 
                FROM users u
                WHERE u.is_active = 1 
                AND (
                    u.last_login >= DATE_SUB(NOW(), INTERVAL 30 DAY)
                    OR EXISTS (
                        SELECT 1 FROM user_sessions s 
                        WHERE s.user_id = u.user_id 
                        AND s.expires_at > NOW()
                    )
                )
            """)
            result = cur.fetchone()
            return result[0] if result else 0
    except Exception:
        # Fallback: assume all users are active if we can't determine
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
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                SELECT COUNT(*) FROM users 
                WHERE last_login >= DATE_SUB(NOW(), INTERVAL %s DAY)
                AND is_active = 1
            """, [days])
            result = cur.fetchone()
            return result[0] if result else 0
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