"""
Admin Dashboard Routes - Phase 1 Implementation

Provides endpoints for the admin dashboard including:
- Dashboard statistics
- Activity feed
- System health monitoring
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from src.Util.db import (
    count_users, count_projects, count_active_sessions,
    get_recent_users_count, get_recent_projects_count,
    get_recent_activity_count, check_database_health, check_redis_health
)
from src.Util.activity_logger import get_recent_activity, count_activity_logs
from src.middleware.authentication import verify_admin_access

# Create router
router = APIRouter(prefix="/admin", tags=["Admin Dashboard"])


@router.get("/dashboard/stats")
async def get_dashboard_stats(
    current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get main dashboard statistics
    
    Returns comprehensive statistics for the admin dashboard including:
    - Total counts (users, projects, sessions)
    - Recent activity counts
    - System health status
    """
    try:
        # Get basic counts
        total_users = count_users()
        total_projects = count_projects()
        active_sessions = count_active_sessions()
        
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
            "growth": {
                "user_growth_7d": user_growth,
                "project_growth_7d": project_growth
            },
            "system_health": {
                "database": db_health,
                "redis": redis_health,
                "overall_status": "healthy" if db_health["status"] == "healthy" and redis_health["status"] == "healthy" else "degraded"
            },
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve dashboard statistics: {str(e)}"
        )


@router.get("/activity")
async def get_activity_feed(
    limit: int = Query(50, ge=1, le=100, description="Number of activities to return"),
    offset: int = Query(0, ge=0, description="Number of activities to skip"),
    activity_type: Optional[str] = Query(None, description="Filter by activity type"),
    user_id: Optional[int] = Query(None, description="Filter by user ID"),
    project_id: Optional[int] = Query(None, description="Filter by project ID"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get activity feed for the dashboard
    
    Returns recent activities with pagination and filtering options.
    Supports filtering by activity type, user, project, and time range.
    """
    try:
        # Get recent activities with filters
        activities = get_recent_activity(
            limit=limit,
            offset=offset,
            user_id=user_id,
            project_id=project_id,
            activity_type=activity_type,
            days=days
        )
        
        # Get total count for pagination
        total_count = count_activity_logs(
            user_id=user_id,
            project_id=project_id,
            activity_type=activity_type,
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
                "activity_type": activity_type,
                "user_id": user_id,
                "project_id": project_id,
                "days": days
            },
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve activity feed: {str(e)}"
        )


@router.get("/health")
async def get_system_health(
    current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get detailed system health information
    
    Returns comprehensive system health data including:
    - Database connectivity and status
    - Redis connectivity and status
    - System metrics and performance indicators
    """
    try:
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
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve system health: {str(e)}"
        )


@router.get("/activity/types")
async def get_activity_types(
    current_user: dict = Depends(verify_admin_access)
) -> Dict[str, Any]:
    """
    Get available activity types for filtering
    
    Returns list of all activity types that have been logged in the system.
    """
    try:
        # This would ideally come from the activity logger enum
        from src.Util.activity_logger import ActivityType
        
        activity_types = [activity_type.value for activity_type in ActivityType]
        
        return {
            "activity_types": activity_types,
            "generated_at": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve activity types: {str(e)}"
        ) 