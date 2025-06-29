"""
Activity Logger Utility

Handles activity logging for the multi-project authentication system.
Provides functions to log user activities, system events, and administrative actions.
"""

import logging
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List

from src.Util.db_config import get_connection

# Configure logging
logger = logging.getLogger(__name__)


class ActivityType(Enum):
    """Enum for different types of activities"""
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_REGISTRATION = "user_registration"
    USER_UPDATE = "user_update"
    USER_STATUS_CHANGE = "user_status_change"
    USER_PASSWORD_RESET = "user_password_reset"
    USER_TYPE_CHANGED = "user_type_changed"
    PROJECT_CREATION = "project_creation"
    PROJECT_UPDATE = "project_update"
    PROJECT_DELETE = "project_delete"
    PROJECT_MEMBER_ADD = "project_member_add"
    PROJECT_MEMBER_REMOVE = "project_member_remove"
    PROJECT_MEMBER_REMOVED = "project_member_removed"
    PROJECT_OWNERSHIP_TRANSFERRED = "project_ownership_transferred"
    PROJECT_ARCHIVED = "project_archived"
    PROJECT_UNARCHIVED = "project_unarchived"
    GROUP_CREATION = "group_creation"
    GROUP_UPDATE = "group_update"
    GROUP_DELETE = "group_delete"
    USER_GROUP_ASSIGN = "user_group_assign"
    USER_GROUP_REMOVE = "user_group_remove"
    PERMISSION_GRANT = "permission_grant"
    PERMISSION_REVOKE = "permission_revoke"
    ROLE_REMOVED = "role_removed"
    BULK_ROLE_ASSIGNMENT = "bulk_role_assignment"
    BULK_GROUP_ASSIGNMENT = "bulk_group_assignment"
    BULK_USER_UPDATE = "bulk_user_update"
    BULK_USER_DELETE = "bulk_user_delete"
    ADMIN_ACTION = "admin_action"
    SYSTEM_EVENT = "system_event"


class ActivityLogger:
    """
    Activity logging system for tracking user and system activities
    """

    @staticmethod
    def log_activity(
            user_id: Optional[int],
            activity_type: str,
            details: Dict[str, Any],
            project_id: Optional[int] = None,
            target_user_id: Optional[int] = None,
            ip_address: Optional[str] = None,
            user_agent: Optional[str] = None
    ) -> bool:
        """
        Log an activity to the database
        
        Args:
            user_id: ID of the user performing the action
            activity_type: Type of activity (use ActivityType enum values)
            details: Additional details about the activity
            project_id: Project ID if applicable
            target_user_id: Target user ID if applicable
            ip_address: IP address of the user
            user_agent: User agent string
            
        Returns:
            Success status
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Insert activity log entry
                cur.execute("""
                            INSERT INTO activity_logs (user_id, activity_type, details, project_id, target_user_id,
                                                       ip_address, user_agent, created_at)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                            """, [
                                user_id, activity_type, str(details), project_id, target_user_id,
                                ip_address, user_agent
                            ])

                con.commit()
                return True

        except Exception as e:
            logger.error(f"Failed to log activity: {str(e)}")
            return False

    @staticmethod
    def get_recent_activity(
            limit: int = 50,
            offset: int = 0,
            user_id: Optional[int] = None,
            project_id: Optional[int] = None,
            activity_type: Optional[str] = None,
            days: int = 30
    ) -> List[Dict[str, Any]]:
        """
        Get recent activities with filtering
        
        Args:
            limit: Maximum number of results
            offset: Number of results to skip
            user_id: Filter by specific user
            project_id: Filter by specific project
            activity_type: Filter by activity type
            days: Number of days to look back
            
        Returns:
            List of activity entries
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Build query with filters
                query = """
                        SELECT al.id,
                               al.user_id,
                               al.activity_type,
                               al.details,
                               al.project_id,
                               al.target_user_id,
                               al.ip_address,
                               al.user_agent,
                               al.created_at,
                               u.username,
                               u.user_hash,
                               p.project_name,
                               p.project_hash,
                               tu.username  as target_username,
                               tu.user_hash as target_user_hash
                        FROM activity_logs al
                                 LEFT JOIN users u ON al.user_id = u.id
                                 LEFT JOIN projects p ON al.project_id = p.id
                                 LEFT JOIN users tu ON al.target_user_id = tu.id
                        WHERE al.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY) \
                        """

                params = [days]

                if user_id:
                    query += " AND al.user_id = %s"
                    params.append(user_id)

                if project_id:
                    query += " AND al.project_id = %s"
                    params.append(project_id)

                if activity_type:
                    query += " AND al.activity_type = %s"
                    params.append(activity_type)

                query += " ORDER BY al.created_at DESC LIMIT %s OFFSET %s"
                params.extend([limit, offset])

                cur.execute(query, params)
                results = cur.fetchall()

                activities = []
                for row in results:
                    activity = {
                        "id": row[0],
                        "user_id": row[1],
                        "activity_type": row[2],
                        "details": row[3],
                        "project_id": row[4],
                        "target_user_id": row[5],
                        "ip_address": row[6],
                        "user_agent": row[7],
                        "created_at": row[8],
                        "username": row[9],
                        "user_hash": row[10],
                        "project_name": row[11],
                        "project_hash": row[12],
                        "target_username": row[13],
                        "target_user_hash": row[14]
                    }
                    activities.append(activity)

                return activities

        except Exception as e:
            logger.error(f"Failed to get recent activity: {str(e)}")
            return []

    @staticmethod
    def count_activity_logs(
            user_id: Optional[int] = None,
            project_id: Optional[int] = None,
            activity_type: Optional[str] = None,
            days: int = 30
    ) -> int:
        """
        Count activity logs with filtering
        
        Args:
            user_id: Filter by specific user
            project_id: Filter by specific project
            activity_type: Filter by activity type
            days: Number of days to look back
            
        Returns:
            Count of matching activities
        """
        try:
            with get_connection() as con:
                cur = con.cursor()

                query = """
                        SELECT COUNT(*)
                        FROM activity_logs
                        WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY) \
                        """

                params = [days]

                if user_id:
                    query += " AND user_id = %s"
                    params.append(user_id)

                if project_id:
                    query += " AND project_id = %s"
                    params.append(project_id)

                if activity_type:
                    query += " AND activity_type = %s"
                    params.append(activity_type)

                cur.execute(query, params)
                result = cur.fetchone()
                return result[0] if result else 0

        except Exception as e:
            logger.error(f"Failed to count activity logs: {str(e)}")
            return 0

    @staticmethod
    def log_user_login(user_id: int, project_id: Optional[int] = None, ip_address: Optional[str] = None,
                       user_agent: Optional[str] = None) -> bool:
        """Log user login activity"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_LOGIN.value,
            details={"action": "login", "timestamp": datetime.utcnow().isoformat()},
            project_id=project_id,
            ip_address=ip_address,
            user_agent=user_agent
        )

    @staticmethod
    def log_user_logout(user_id: int, project_id: Optional[int] = None, ip_address: Optional[str] = None) -> bool:
        """Log user logout activity"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_LOGOUT.value,
            details={"action": "logout", "timestamp": datetime.utcnow().isoformat()},
            project_id=project_id,
            ip_address=ip_address
        )

    @staticmethod
    def log_user_registration(user_id: int, project_id: Optional[int] = None, ip_address: Optional[str] = None) -> bool:
        """Log user registration activity"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.USER_REGISTRATION.value,
            details={"action": "registration", "timestamp": datetime.utcnow().isoformat()},
            project_id=project_id,
            ip_address=ip_address
        )

    @staticmethod
    def log_admin_action(user_id: int, action: str, details: Dict[str, Any], project_id: Optional[int] = None,
                         target_user_id: Optional[int] = None) -> bool:
        """Log administrative actions"""
        return ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=ActivityType.ADMIN_ACTION.value,
            details={"action": action, "details": details, "timestamp": datetime.utcnow().isoformat()},
            project_id=project_id,
            target_user_id=target_user_id
        )


# Global activity logger instance
activity_logger = ActivityLogger()


# Convenience functions
def log_activity(user_id: Optional[int], activity_type: str, details: Dict[str, Any], **kwargs) -> bool:
    """Convenience function for logging activities"""
    return activity_logger.log_activity(user_id, activity_type, details, **kwargs)


def get_recent_activity(limit: int = 50, **kwargs) -> List[Dict[str, Any]]:
    """Convenience function for getting recent activities"""
    return activity_logger.get_recent_activity(limit, **kwargs)


def count_activity_logs(**kwargs) -> int:
    """Convenience function for counting activity logs"""
    return activity_logger.count_activity_logs(**kwargs)
