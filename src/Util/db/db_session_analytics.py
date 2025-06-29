"""
Session Analytics and Activity Database Functions

Provides database functions for session management, activity tracking,
and analytics support for the multi-project authentication system.
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from src.Util.db_config import get_connection, redis_client

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
        # Count session keys in Redis
        session_keys = redis_client.keys("session:*")
        return len(session_keys)
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

def get_user_status(user_id: int) -> Optional[bool]:
    """
    Get user's active status
    
    Args:
        user_id: User ID
        
    Returns:
        User's active status or None if not found
    """
    try:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("SELECT is_active FROM users WHERE id = %s", [user_id])
            result = cur.fetchone()
            return bool(result[0]) if result else None
    except Exception as e:
        logger.error(f"Failed to get user status: {str(e)}")
        return None


def set_user_status(user_id: int, is_active: bool, updated_by: Optional[int] = None) -> bool:
    """
    Set user's active status
    
    Args:
        user_id: User ID
        is_active: New active status
        updated_by: ID of user making the change
        
    Returns:
        Success status
    """
    try:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                        UPDATE users
                        SET is_active  = %s,
                            updated_at = NOW()
                        WHERE id = %s
                        """, [is_active, user_id])

            success = cur.rowcount > 0
            if success:
                con.commit()

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

    except Exception as e:
        logger.error(f"Failed to set user status: {str(e)}")
        return False


def get_recent_users_count(days: int = 30) -> int:
    """
    Get count of users created in the last N days
    
    Args:
        days: Number of days to look back
        
    Returns:
        Count of recent users
    """
    try:
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
    except Exception as e:
        logger.error(f"Failed to get recent users count: {str(e)}")
        return 0


def get_user_login_statistics(days: int = 30) -> Dict[str, Any]:
    """
    Get user login statistics
    
    Args:
        days: Number of days to look back
        
    Returns:
        Dictionary with login statistics
    """
    try:
        with get_connection() as con:
            cur = con.cursor()

            # Try to get login stats from activity logs (if table exists)
            try:
                cur.execute("""
                            SELECT COUNT(*)
                            FROM activity_logs
                            WHERE activity_type = 'user_login'
                              AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                            """, [days])
                login_count = cur.fetchone()[0]

                cur.execute("""
                            SELECT COUNT(DISTINCT user_id)
                            FROM activity_logs
                            WHERE activity_type = 'user_login'
                              AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                            """, [days])
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

    except Exception as e:
        logger.error(f"Failed to get login statistics: {str(e)}")
        return {"total_logins": 0, "unique_users": 0, "period_days": days, "source": "error"}


# =================== PROJECT ANALYTICS ===================

def get_recent_projects_count(days: int = 30) -> int:
    """
    Get count of projects created in the last N days
    
    Args:
        days: Number of days to look back
        
    Returns:
        Count of recent projects
    """
    try:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("""
                        SELECT COUNT(*)
                        FROM projects
                        WHERE project_created >= DATE_SUB(NOW(), INTERVAL %s DAY)
                          AND is_active = 1
                        """, [days])
            result = cur.fetchone()
            return result[0] if result else 0
    except Exception as e:
        logger.error(f"Failed to get recent projects count: {str(e)}")
        return 0


def get_project_members(project_id: int) -> List[Dict[str, Any]]:
    """
    Get all members of a project with their access details
    
    Args:
        project_id: Project ID
        
    Returns:
        List of project members with details
    """
    try:
        with get_connection() as con:
            cur = con.cursor()

            # Query to get all users with access to this project
            cur.execute("""
                        SELECT DISTINCT u.id,
                                        u.user_hash,
                                        u.username,
                                        u.email,
                                        u.user_type,
                                        u.is_active,
                                        u.created_at,
                                        up.granted_at,
                                        up.granted_by,
                                        apa.assigned_at as admin_assigned_at
                        FROM users u
                                 LEFT JOIN user_projects up
                                           ON u.id = up.user_id AND up.project_id = %s AND up.is_active = 1
                                 LEFT JOIN admin_project_assignments apa
                                           ON u.id = apa.user_id AND apa.project_id = %s AND apa.is_active = 1
                        WHERE u.is_active = 1
                          AND (
                            u.user_type = 'root' OR
                            (u.user_type = 'admin' AND apa.user_id IS NOT NULL) OR
                            (u.user_type = 'consumer' AND up.user_id IS NOT NULL)
                            )
                        ORDER BY u.user_type, u.username
                        """, [project_id, project_id])

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
                    "granted_at": row[7] or row[9],  # Use appropriate date based on user type
                    "granted_by": row[8],
                    "access_type": "admin" if row[4] == "admin" else ("root" if row[4] == "root" else "consumer")
                }
                members.append(member)

            return members

    except Exception as e:
        logger.error(f"Failed to get project members: {str(e)}")
        return []


def add_user_to_project(user_id: int, project_id: int, assigned_by: Optional[int] = None) -> bool:
    """
    Add a user to a project (for consumer users)
    
    Args:
        user_id: User ID
        project_id: Project ID
        assigned_by: ID of user making the assignment
        
    Returns:
        Success status
    """
    try:
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

    except Exception as e:
        logger.error(f"Failed to add user to project: {str(e)}")
        return False


# =================== SYSTEM HEALTH ===================

def check_database_health() -> Dict[str, Any]:
    """
    Check database connectivity and health
    
    Returns:
        Database health information
    """
    try:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("SELECT 1")
            cur.fetchone()

        return {
            "status": "healthy",
            "message": "Database accessible",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Database error: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }


def check_redis_health() -> Dict[str, Any]:
    """
    Check Redis connectivity and health
    
    Returns:
        Redis health information
    """
    try:
        redis_client.ping()
        return {
            "status": "healthy",
            "message": "Redis accessible",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "message": f"Redis error: {str(e)}",
            "timestamp": datetime.utcnow().isoformat()
        }


# =================== ACTIVITY LOGS INTEGRATION ===================

def get_recent_activity_count(days: int = 7) -> int:
    """
    Get count of recent activities
    
    Args:
        days: Number of days to look back
        
    Returns:
        Count of recent activities
    """
    try:
        # Try to use activity logs if available
        from src.Util.activity_logger import count_activity_logs
        return count_activity_logs(days=days)
    except Exception:
        # Fallback: estimate based on user and project activity
        try:
            recent_users = get_recent_users_count(days)
            recent_projects = get_recent_projects_count(days)
            active_sessions = count_active_sessions()

            # Rough estimate of activity
            return recent_users + recent_projects + (active_sessions // 10)
        except Exception as e:
            logger.error(f"Failed to get recent activity count: {str(e)}")
            return 0


def initialize_activity_logs_table() -> bool:
    """
    Initialize the activity_logs table if it doesn't exist
    
    Returns:
        Success status
    """
    try:
        with get_connection() as con:
            cur = con.cursor()

            # Create activity_logs table
            cur.execute("""
                        CREATE TABLE IF NOT EXISTS activity_logs
                        (
                            id
                            BIGINT
                            UNSIGNED
                            AUTO_INCREMENT
                            PRIMARY
                            KEY,
                            user_id
                            INT
                            UNSIGNED,
                            activity_type
                            VARCHAR
                        (
                            50
                        ) NOT NULL,
                            details TEXT,
                            project_id INT UNSIGNED,
                            target_user_id INT UNSIGNED,
                            ip_address VARCHAR
                        (
                            45
                        ),
                            user_agent TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_user_id
                        (
                            user_id
                        ),
                            INDEX idx_activity_type
                        (
                            activity_type
                        ),
                            INDEX idx_project_id
                        (
                            project_id
                        ),
                            INDEX idx_created_at
                        (
                            created_at
                        ),
                            INDEX idx_target_user_id
                        (
                            target_user_id
                        ),
                            FOREIGN KEY
                        (
                            user_id
                        ) REFERENCES users
                        (
                            id
                        ) ON DELETE SET NULL,
                            FOREIGN KEY
                        (
                            project_id
                        ) REFERENCES projects
                        (
                            id
                        )
                          ON DELETE SET NULL,
                            FOREIGN KEY
                        (
                            target_user_id
                        ) REFERENCES users
                        (
                            id
                        )
                          ON DELETE SET NULL
                            )
                        """)

            con.commit()
            logger.info("Activity logs table initialized successfully")
            return True

    except Exception as e:
        logger.error(f"Failed to initialize activity logs table: {str(e)}")
        return False
