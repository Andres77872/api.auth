"""
Session Analytics and Activity Database Functions

Provides database functions for session management, activity tracking,
and analytics support for the multi-project authentication system.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from src.Util.db_config import get_connection, redis_client
from src.Util.db_error_wrapper import handle_db_operation

# Configure logging
logger = logging.getLogger(__name__)


# =================== SESSION ANALYTICS ===================

def count_active_sessions() -> int:
    """
    Count active sessions in Redis
    
    Returns:
        Number of active sessions
    """
    try:
        return sum(1 for _ in redis_client.scan_iter(match="session:*", count=100))
    except Exception as e:
        logger.error(f"Failed to count active sessions: {str(e)}")
        return 0


def get_session_statistics() -> Dict[str, Any]:
    """
    Get comprehensive session statistics
    
    Returns:
        Dictionary with session statistics
    """
    try:
        # Get active sessions count
        active_sessions = count_active_sessions()

        # Get session distribution by user type (if possible)
        session_info = {
            "active_sessions": active_sessions,
            "redis_available": True
        }

        # Try to get more detailed session info
        try:
            info = redis_client.info()
            session_info.update({
                "redis_memory": info.get("used_memory_human", "unknown"),
                "redis_uptime": info.get("uptime_in_seconds", 0)
            })
        except:
            pass

        return session_info

    except Exception as e:
        logger.error(f"Failed to get session statistics: {str(e)}")
        return {"active_sessions": 0, "redis_available": False}


# =================== USER ANALYTICS ===================

def get_user_status(user_id: str) -> Optional[bool]:
    """
    Get user's active status.
    
    Args:
        user_id: User ID
        
    Returns:
        User's active status or None if not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_status', [user_id])
            result = cur.fetchone()
            return bool(result[0]) if result else None
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_status(user_id={user_id})"
    )


def set_user_status(user_id: str, is_active: bool, updated_by: Optional[str] = None) -> bool:
    """
    Set user's active status.
    
    Args:
        user_id: User ID
        is_active: New active status
        updated_by: ID of user making the change
        
    Returns:
        True if status set successfully
        
    Raises:
        NotFoundError: If user not found
        DatabaseError: On database operation errors
    """
    def _set():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_set_user_status', [user_id, is_active])
            con.commit()
            success = True

            # Log the status change
            try:
                from src.Util.activity_logger import ActivityType, log_activity
                log_activity(
                    user_id=updated_by,
                    activity_type=ActivityType.USER_STATUS_CHANGE.value,
                    details={
                        "target_user_id": user_id,
                        "new_status": "active" if is_active else "inactive",
                        "action": "activate" if is_active else "deactivate"
                    },
                    target_user_id=user_id
                )
            except:
                pass  # Don't fail if activity logging fails

            return success
    
    return handle_db_operation(
        _set,
        error_context=f"set_user_status(user_id={user_id}, is_active={is_active})"
    )


def get_recent_users_count(days: int = 30) -> int:
    """
    Get count of users created in the last N days.
    
    Args:
        days: Number of days to look back
        
    Returns:
        Count of recent users (0 on error)
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns 0 on error to prevent breaking analytics dashboards.
    """
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_recent_users_count', [days])
            result = cur.fetchone()
            return result[0] if result else 0
    
    return handle_db_operation(
        _count,
        error_context=f"get_recent_users_count(days={days})",
        default_return=0
    )


def get_user_login_statistics(days: int = 30) -> Dict[str, Any]:
    """
    Get user login statistics.
    
    Args:
        days: Number of days to look back
        
    Returns:
        Dictionary with login statistics (error dict on failure)
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns safe error dict to prevent breaking analytics dashboards.
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()

            # Try to get login stats from activity logs (if table exists)
            try:
                cur.callproc('sp_get_login_statistics', [days])
                login_count = cur.fetchone()[0]
                cur.nextset()
                unique_users = cur.fetchone()[0]

                return {
                    "total_logins": login_count,
                    "unique_users": unique_users,
                    "period_days": days,
                    "source": "activity_logs"
                }

            except Exception:
                # Fallback: estimate based on user creation and session data
                recent_users = get_recent_users_count(days)
                active_sessions = count_active_sessions()

                # Rough estimation
                estimated_logins = max(recent_users, active_sessions) * 2

                return {
                    "total_logins": estimated_logins,
                    "unique_users": recent_users,
                    "period_days": days,
                    "source": "estimated"
                }
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_login_statistics(days={days})",
        default_return={"total_logins": 0, "unique_users": 0, "period_days": days, "source": "error"}
    )


# =================== PROJECT ANALYTICS ===================

def get_recent_projects_count(days: int = 30) -> int:
    """
    Get count of projects created in the last N days.
    
    Args:
        days: Number of days to look back
        
    Returns:
        Count of recent projects (0 on error)
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns 0 on error to prevent breaking analytics dashboards.
    """
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_recent_projects_count', [days])
            result = cur.fetchone()
            return result[0] if result else 0
    
    return handle_db_operation(
        _count,
        error_context=f"get_recent_projects_count(days={days})",
        default_return=0
    )


def get_project_members(project_id: str) -> List[Dict[str, Any]]:
    """
    Get all members of a project with their access details.
    
    Args:
        project_id: Project ID
        
    Returns:
        List of project members with details (empty list on error)
        
    Raises:
        DatabaseError: On database operation errors
        
    Note:
        Returns empty list on error to prevent breaking dashboards.
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_members', [project_id])
            results = cur.fetchall()

            members = []
            for row in results:
                member = {
                    "user_id": row[0],
                    "user_hash": row[1],
                    "username": row[2],
                    "email": row[3],
                    "user_type": row[4],
                    "is_active": bool(row[5]),
                    "created_at": row[6],
                    "granted_at": row[7],
                    "granted_by": row[8],
                    "access_through_group": row[9],
                    "access_type": "root" if row[4] == "root" else ("admin" if row[4] == "admin" else "consumer")
                }
                members.append(member)

            return members
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_members(project_id={project_id})",
        default_return=[]
    )


def add_user_to_project(user_id: str, project_id: str, assigned_by: Optional[str] = None) -> bool:
    """
    Add a user to a project (for consumer users).
    
    Args:
        user_id: User ID
        project_id: Project ID
        assigned_by: ID of user making the assignment
        
    Returns:
        True if added successfully
        
    Raises:
        NotFoundError: If user not found
        ValidationError: If user type invalid
        DatabaseError: On database operation errors
    """
    def _add():
        # Import here to avoid circular imports
        from src.Util.db import grant_user_project_access, get_user_by_id

        # Get user to check type
        user = get_user_by_id(user_id)
        if not user:
            return False

        if user.user_type == 'consumer':
            # Grant project access for consumer users
            result = grant_user_project_access(user_id, project_id, granted_by=assigned_by)

            if result:
                # Log the action
                try:
                    from src.Util.activity_logger import ActivityType, log_activity
                    log_activity(
                        user_id=assigned_by,
                        activity_type=ActivityType.PROJECT_MEMBER_ADD.value,
                        details={
                            "target_user_id": user_id,
                            "project_id": project_id,
                            "action": "add_consumer_to_project"
                        },
                        project_id=project_id,
                        target_user_id=user_id
                    )
                except:
                    pass

            return result is not None

        elif user.user_type == 'admin':
            # Add admin to project
            from src.Util.db import add_admin_to_project
            success = add_admin_to_project(user_id, project_id, assigned_by=assigned_by)

            if success:
                # Log the action
                try:
                    from src.Util.activity_logger import ActivityType, log_activity
                    log_activity(
                        user_id=assigned_by,
                        activity_type=ActivityType.PROJECT_MEMBER_ADD.value,
                        details={
                            "target_user_id": user_id,
                            "project_id": project_id,
                            "action": "add_admin_to_project"
                        },
                        project_id=project_id,
                        target_user_id=user_id
                    )
                except:
                    pass

            return success

        # Root users automatically have access to all projects
        return user.user_type == 'root'
    
    return handle_db_operation(
        _add,
        error_context=f"add_user_to_project(user_id={user_id}, project_id={project_id})"
    )


# =================== SYSTEM HEALTH ===================

def check_database_health() -> Dict[str, Any]:
    """
    Check database connectivity and health.
    
    Returns:
        Database health information (never raises exceptions)
        
    Note:
        Always returns a dict with health status, never fails.
    """
    def _check():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_check_database_health', [])
            cur.fetchone()

        return {
            "status": "healthy",
            "message": "Database accessible",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
    
    return handle_db_operation(
        _check,
        error_context="check_database_health()",
        default_return={
            "status": "unhealthy",
            "message": "Database error",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
    )


def check_redis_health() -> Dict[str, Any]:
    """
    Check Redis connectivity and health.
    
    Returns:
        Redis health information (never raises exceptions)
        
    Note:
        Always returns a dict with health status, never fails.
    """
    try:
        redis_client.ping()
        return {
            "status": "healthy",
            "message": "Redis accessible",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Redis error: {str(e)}",
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        }


# =================== ACTIVITY LOGS INTEGRATION ===================

def get_recent_activity_count(days: int = 7) -> int:
    """
    Get count of recent activities.
    
    Args:
        days: Number of days to look back
        
    Returns:
        Count of recent activities (0 on error)
        
    Note:
        Returns 0 on error to prevent breaking dashboards.
    """
    def _count():
        # Try to use activity logs if available
        try:
            from src.Util.activity_logger import count_activity_logs
            return count_activity_logs(days=days)
        except Exception:
            # Fallback: estimate based on user and project activity
            recent_users = get_recent_users_count(days)
            recent_projects = get_recent_projects_count(days)
            active_sessions = count_active_sessions()

            # Rough estimate of activity
            return recent_users + recent_projects + (active_sessions // 10)
    
    return handle_db_operation(
        _count,
        error_context=f"get_recent_activity_count(days={days})",
        default_return=0
    )


def initialize_activity_logs_table() -> bool:
    """Initialize the activity_logs table if it doesn't exist
    
    Note: This function is deprecated as the table is now created in the schema files.
    
    Returns:
        Success status
    """
    try:
        logger.info("Activity logs table should be created via schema files (02_create_tables.sql)")
        return True

    except Exception as e:
        logger.error(f"Note: {str(e)}")
        return False
